#!/usr/bin/env python3
"""Publish an explicit static-file allowlist. Python standard library + AWS CLI v2."""
import argparse
import base64
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid


CONTENT_TYPES = {
    '.html': 'text/html; charset=utf-8',
    '.js': 'text/javascript; charset=utf-8',
    '.css': 'text/css; charset=utf-8',
    '.svg': 'image/svg+xml',
    '.png': 'image/png',
    '.jpg': 'image/jpeg',
    '.jpeg': 'image/jpeg',
    '.webp': 'image/webp',
    '.ico': 'image/x-icon',
    '.woff': 'font/woff',
    '.woff2': 'font/woff2',
}
MAX_FILE_BYTES = 25 * 1024 * 1024
MAX_TOTAL_BYTES = 100 * 1024 * 1024


def require(condition, message):
    if not condition:
        raise ValueError(message)


def digest(content):
    return hashlib.sha256(content).hexdigest()


def load_configuration(root):
    directory = root / 'infrastructure/aws'
    config = json.loads((directory / 'deploy-config.json').read_text())
    require(config['repository'] == 'Moss-libe/alphaclawr' and config['branch'] == 'main',
            'The deployment target must be this repository and main branch.')
    require(re.fullmatch(r'[0-9]{12}', config['aws_account_id']), 'Invalid target account.')
    require(config['deploy_role_arn'] ==
            f"arn:aws:iam::{config['aws_account_id']}:role/alphawalk-github-deploy", 'Unexpected deployment role.')
    require(config['aws_region'] == 'us-east-1', 'Unexpected deployment Region.')
    require(re.fullmatch(r'[a-z0-9][a-z0-9.-]{1,61}[a-z0-9]', config['website_bucket']), 'Invalid bucket name.')
    require(re.fullmatch(r'[A-Z0-9]+', config['cloudfront_distribution_id']), 'Invalid distribution ID.')
    require(re.fullmatch(r'https://[a-z0-9]+\.execute-api\.us-east-1\.amazonaws\.com/subscribe',
                         config['subscription_api_url']), 'Use the complete new API URL without /prod.')
    require(config['website_origins'][:2] == ['https://alphawalk.ai', 'https://www.alphawalk.ai'],
            'The official website origins must remain explicit.')
    for origin in config['website_origins']:
        parsed = urllib.parse.urlsplit(origin)
        require(parsed.scheme == 'https' and parsed.hostname and not parsed.username and not parsed.password
                and parsed.port is None and not parsed.path and not parsed.query and not parsed.fragment,
                'Website origins must be bare HTTPS origins.')
    paths = [line.strip() for line in (directory / 'website-files.txt').read_text().splitlines()
             if line.strip() and not line.lstrip().startswith('#')]
    require(paths and len(paths) == len(set(paths)), 'The upload allowlist is empty or has duplicate entries.')
    require({'index.html', 'email-submit.js'} <= set(paths), 'Required website entry points are missing.')
    policy = json.loads((directory / 'github-publish-role.json').read_text())
    parameters = policy['Parameters']
    require(parameters['WebsiteBucketName']['Default'] == config['website_bucket'], 'IAM and upload buckets differ.')
    require(parameters['WebsiteDistributionId']['Default'] == config['cloudfront_distribution_id'],
            'IAM and upload distributions differ.')
    role = policy['Resources']['GitHubWebsiteDeployRole']['Properties']
    require(set(policy['Resources']) == {'GitHubWebsiteDeployRole'}, 'Publishing stack must only manage its dedicated role.')
    require(role['RoleName'] == 'alphawalk-github-deploy', 'Unexpected IAM role name.')
    provider = f"arn:aws:iam::{config['aws_account_id']}:oidc-provider/token.actions.githubusercontent.com"
    require(parameters['GitHubOidcProviderArn']['Default'] == provider, 'Wrong OIDC provider account.')
    subject_pattern = r'^repo:(Moss-libe/alphaclawr|Moss-libe@[0-9]+/alphaclawr@[0-9]+):ref:refs/heads/main$'
    require(parameters['GitHubOidcSubject']['AllowedPattern'] == subject_pattern,
            'The trusted subject must stay restricted to this repository and main.')
    trust = role['AssumeRolePolicyDocument']['Statement']
    require(trust == [{'Effect': 'Allow', 'Principal': {'Federated': {'Ref': 'GitHubOidcProviderArn'}},
                      'Action': 'sts:AssumeRoleWithWebIdentity', 'Condition': {'StringEquals': {
                          'token.actions.githubusercontent.com:aud': 'sts.amazonaws.com',
                          'token.actions.githubusercontent.com:sub': {'Ref': 'GitHubOidcSubject'}}}}],
            'OIDC trust must use an exact audience and one exact repository/main subject.')
    statements = role['Policies'][0]['PolicyDocument']['Statement']
    require(statements[0]['Action'] == ['s3:GetObject', 's3:PutObject'], 'Unexpected S3 deployment permissions.')
    granted = {entry['Fn::Sub'] for entry in statements[0]['Resource']}
    expected = {'arn:${AWS::Partition}:s3:::${WebsiteBucketName}/' + path for path in paths}
    require(granted == expected, 'The S3 object permissions must exactly match the upload allowlist.')
    require(statements[1]['Action'] == ['cloudfront:CreateInvalidation', 'cloudfront:GetInvalidation'],
            'Unexpected CloudFront deployment permissions.')
    require(statements[1]['Resource'] == {'Fn::Sub':
            'arn:${AWS::Partition}:cloudfront::${AWS::AccountId}:distribution/${WebsiteDistributionId}'},
            'CloudFront permissions must target one distribution.')
    require(len(statements) == 2 and len(role['Policies']) == 1 and not role.get('ManagedPolicyArns'),
            'Deployment role must not include additional policies.')
    return config, paths


def prepare(root, destination, config, paths):
    manifest = []
    total = 0
    for path in paths:
        logical = PurePosixPath(path)
        require(not logical.is_absolute() and re.fullmatch(r'[A-Za-z0-9_./-]+', path)
                and all(part not in ('.', '..') and not part.startswith('.') for part in logical.parts),
                f'Unsafe upload path: {path}')
        require(not any(part.lower() in ('infrastructure', 'scripts', 'node_modules')
                        or part.lower().startswith('readme') for part in logical.parts),
                f'Non-site file in upload allowlist: {path}')
        source = root / path
        for partial in [source, *source.parents]:
            if partial == root:
                break
            require(not partial.is_symlink(), f'Symlinks are not uploaded: {path}')
        require(source.is_file() and source.resolve().is_relative_to(root), f'Missing or unsafe source: {path}')
        suffix = source.suffix.lower()
        require(suffix in CONTENT_TYPES, f'Unsupported static content type: {path}')
        content = source.read_bytes()
        require(len(content) <= MAX_FILE_BYTES, f'File is unexpectedly large: {path}')
        total += len(content)
        require(total <= MAX_TOTAL_BYTES, 'The static upload exceeds the total size limit.')
        if suffix in ('.html', '.js'):
            text = content.decode('utf-8')
            endpoints = re.findall(r'https://[a-z0-9]+\.execute-api\.[a-z0-9-]+\.amazonaws\.com/[^\s\"\x27<>`]*', text)
            require(all(endpoint == config['subscription_api_url'] for endpoint in endpoints),
                    f'Unexpected or old API endpoint in {path}')
            if path == 'email-submit.js':
                require(config['subscription_api_url'] in text, 'email-submit.js does not use the new API.')
        target = destination / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(content)
        manifest.append({'path': path, 'size': len(content), 'sha256': digest(content),
                         'content_type': CONTENT_TYPES[suffix],
                         'cache_control': 'no-cache' if suffix in ('.html', '.js', '.css') else 'public, max-age=86400'})
    return manifest


def aws(config, *args, timeout=120):
    command = ['aws', '--region', config['aws_region'], '--no-cli-pager', '--output', 'json', *args]
    result = subprocess.run(command, check=True, capture_output=True, text=True, timeout=timeout)
    return json.loads(result.stdout) if result.stdout.strip() else {}


def assert_deployment_context(config):
    require(os.environ.get('GITHUB_ACTIONS') == 'true', 'Deployment runs only in the reviewed GitHub workflow.')
    require(os.environ.get('GITHUB_REPOSITORY') == config['repository'], 'Wrong GitHub repository.')
    require(os.environ.get('GITHUB_REF') == 'refs/heads/main', 'Only main can deploy.')
    require(os.environ.get('GITHUB_EVENT_NAME') in ('push', 'workflow_dispatch'), 'PRs cannot deploy.')
    identity = aws(config, 'sts', 'get-caller-identity')
    require(identity.get('Account') == config['aws_account_id'], 'AWS credentials belong to another account.')
    expected = f"arn:aws:sts::{config['aws_account_id']}:assumed-role/alphawalk-github-deploy/"
    require(identity.get('Arn', '').startswith(expected), 'AWS credentials are not the dedicated publishing role.')


def publish(config, destination, manifest):
    assert_deployment_context(config)
    # Write resources first, then secondary pages, and the home page last.
    ordered = sorted(manifest, key=lambda item: (item['path'] == 'index.html',
                                                item['path'].endswith('.html'), item['path']))
    for item in ordered:
        checksum = base64.b64encode(bytes.fromhex(item['sha256'])).decode()
        aws(config, 's3api', 'put-object', '--bucket', config['website_bucket'], '--key', item['path'],
            '--body', str(destination / item['path']), '--content-type', item['content_type'],
            '--cache-control', item['cache_control'], '--server-side-encryption', 'AES256',
            '--checksum-sha256', checksum, '--expected-bucket-owner', config['aws_account_id'])
        stored = aws(config, 's3api', 'head-object', '--bucket', config['website_bucket'], '--key', item['path'],
                     '--checksum-mode', 'ENABLED', '--expected-bucket-owner', config['aws_account_id'])
        require(stored.get('ChecksumSHA256') == checksum and stored.get('ContentLength') == item['size'],
                f'S3 content verification failed: {item["path"]}')
        require(stored.get('CacheControl') == item['cache_control'] and stored.get('ContentType') == item['content_type'],
                f'S3 metadata verification failed: {item["path"]}')
        print(f'Uploaded and verified {item["path"]}', flush=True)
    paths = ['/'] + ['/' + item['path'] for item in manifest]
    reference = 'alphawalk-' + os.environ.get('GITHUB_RUN_ID', str(uuid.uuid4())) + '-' + os.environ.get('GITHUB_RUN_ATTEMPT', '1')
    batch = {'Paths': {'Quantity': len(paths), 'Items': paths}, 'CallerReference': reference}
    invalidation = aws(config, 'cloudfront', 'create-invalidation', '--distribution-id', config['cloudfront_distribution_id'],
                       '--invalidation-batch', json.dumps(batch))
    invalidation_id = invalidation['Invalidation']['Id']
    print(f'Waiting for CloudFront invalidation {invalidation_id}', flush=True)
    aws(config, 'cloudfront', 'wait', 'invalidation-completed', '--distribution-id',
        config['cloudfront_distribution_id'], '--id', invalidation_id, timeout=650)
    return invalidation_id


def request(url, *, method='GET', headers=None, body=None):
    merged = {'Accept-Encoding': 'identity', 'User-Agent': 'AlphaWalk-deployment-verification/1.0'}
    merged.update(headers or {})
    req = urllib.request.Request(url, data=body, headers=merged, method=method)
    try:
        response = urllib.request.urlopen(req, timeout=30)
    except urllib.error.HTTPError as error:
        response = error
    with response:
        content = response.read(MAX_FILE_BYTES + 1)
        require(len(content) <= MAX_FILE_BYTES, 'Verification response is unexpectedly large.')
        return response.status, response.headers, content


def verify_live(config, manifest):
    lookup = {item['path']: item for item in manifest}
    checked = 0
    for index, origin in enumerate(config['website_origins']):
        paths = list(lookup) if index == 0 else ['index.html', 'email-submit.js']
        for path in paths:
            item = lookup[path]
            url = origin + ('/' if path == 'index.html' else '/' + urllib.parse.quote(path, safe='/'))
            last_error = None
            for attempt in range(4):
                try:
                    status, headers, content = request(url)
                    require(status == 200 and digest(content) == item['sha256'], f'HTTPS content mismatch: {url}')
                    require(headers.get('Cache-Control', '').replace(' ', '') == item['cache_control'].replace(' ', ''),
                            f'Cache header mismatch: {url}')
                    require(headers.get_content_type() == item['content_type'].split(';')[0], f'Content type mismatch: {url}')
                    last_error = None
                    break
                except (ValueError, urllib.error.URLError, TimeoutError) as error:
                    last_error = error
                    if attempt < 3:
                        time.sleep(5)
            if last_error:
                raise last_error
            checked += 1
        status, headers, _ = request(config['subscription_api_url'], method='OPTIONS', headers={
            'Origin': origin, 'Access-Control-Request-Method': 'POST', 'Access-Control-Request-Headers': 'content-type'})
        require(status in (200, 204) and headers.get('Access-Control-Allow-Origin') == origin,
                f'API CORS origin verification failed: {origin}')
        require('POST' in headers.get('Access-Control-Allow-Methods', '').upper()
                and 'content-type' in headers.get('Access-Control-Allow-Headers', '').lower(), 'API CORS methods/headers failed.')
    # Invalid input exercises the new API without adding a subscriber or requiring DynamoDB permissions.
    status, headers, body = request(config['subscription_api_url'], method='POST',
        headers={'Content-Type': 'application/json', 'Origin': config['website_origins'][0]},
        body=b'{"email":"invalid-address"}')
    require(status == 400 and json.loads(body).get('success') is False, 'API invalid-input behavior changed.')
    require(headers.get('Access-Control-Allow-Origin') == config['website_origins'][0], 'API POST CORS failed.')
    return checked


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command', choices=['validate', 'deploy', 'verify'])
    parser.add_argument('--root', type=Path, default=Path(__file__).resolve().parents[1])
    args = parser.parse_args()
    root = args.root.resolve(strict=True)
    config, paths = load_configuration(root)
    with tempfile.TemporaryDirectory(prefix='alphawalk-static-') as temporary:
        destination = Path(temporary)
        manifest = prepare(root, destination, config, paths)
        print(json.dumps({'command': args.command, 'file_count': len(manifest), 'total_bytes': sum(x['size'] for x in manifest),
                          'bucket': config['website_bucket'], 'distribution': config['cloudfront_distribution_id'],
                          'subscription_api_url': config['subscription_api_url'], 'files': manifest}, indent=2), flush=True)
        invalidation = publish(config, destination, manifest) if args.command == 'deploy' else None
        checked = verify_live(config, manifest) if args.command in ('deploy', 'verify') else 0
        if args.command == 'deploy':
            print(f'Deployment verified: {checked} HTTPS responses, exact API URL, CORS and invalid-input response.')
            summary_path = os.environ.get('GITHUB_STEP_SUMMARY')
            if summary_path:
                with open(summary_path, 'a', encoding='utf-8') as summary:
                    summary.write(f'## Website published\n\n- Revision: `{os.environ.get("GITHUB_SHA", "unknown")}`\n'
                                  f'- Files uploaded: {len(manifest)}\n- HTTPS responses checked: {checked}\n'
                                  f'- CloudFront invalidation: `{invalidation}`\n'
                                  '- New subscription API and CORS verified; no test subscriber was added.\n')


if __name__ == '__main__':
    try:
        main()
    except (ValueError, OSError, subprocess.SubprocessError, KeyError, json.JSONDecodeError) as error:
        print(f'Deployment failed: {error}', file=sys.stderr)
        if isinstance(error, subprocess.CalledProcessError) and error.stderr:
            print(error.stderr.strip(), file=sys.stderr)
        sys.exit(1)
