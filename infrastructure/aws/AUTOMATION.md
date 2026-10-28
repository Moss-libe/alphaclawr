# Static website publishing with GitHub Actions

This workflow publishes the existing website to the new AWS account. It does not deploy CloudFormation, change IAM or domains, manage DynamoDB, or call the previous AWS hosting service.

## Files and boundaries

| File | Purpose |
| --- | --- |
| `.github/workflows/deploy-website.yml` | Validate pull requests; publish main pushes and manual runs on main |
| `scripts/deploy_website.py` | Validate and stage the allowlist, upload each object, invalidate CloudFront, verify live content |
| `infrastructure/aws/website-files.txt` | The exact 19 static files permitted for upload |
| `infrastructure/aws/deploy-config.json` | Public deployment targets and the complete current subscription API URL |
| `infrastructure/aws/github-publish-role.json` | A separate CloudFormation template for the publishing role only |

The existing website stack remains `alphawalk-website` in `us-east-1`. Manage infrastructure changes manually through its reviewed CloudFormation change sets.

The publishing targets are:

- S3: `alphawalk-website-websitebucket-79ikctfx7zzd`
- CloudFront: `E8NOVXBQ9GKY6`
- Role: `arn:aws:iam::739871967026:role/alphawalk-github-deploy`
- Subscription API: `https://6a532z2rr8.execute-api.us-east-1.amazonaws.com/subscribe`

These identifiers are public configuration, not credentials. No long-lived AWS access key or GitHub secret is needed.

## One-time setup

1. Confirm the AWS account is the intended new account and the existing provider `token.actions.githubusercontent.com` includes audience `sts.amazonaws.com`. The role template reuses that provider and neither creates nor edits it.
2. Determine the repository's exact OIDC subject before creating the role. The default template value is:

   ```text
   repo:Moss-libe/alphaclawr:ref:refs/heads/main
   ```

   GitHub also supports immutable subjects, including owner and repository IDs:

   ```text
   repo:Moss-libe@OWNER_ID/alphaclawr@REPOSITORY_ID:ref:refs/heads/main
   ```

   Repositories created before 2026-07-15 generally keep the old format, but opt-in, rename, or transfer may change it. Inspect the GitHub OIDC settings or the read-only endpoint `GET /repos/Moss-libe/alphaclawr/actions/oidc/customization/sub`. If the response does not establish the actual format, use an approved main-branch diagnostic that requests a GitHub OIDC token and reports only `aud` and `sub`; never print the JWT or request token. Set `GitHubOidcSubject` to the actual exact value. Do not solve a mismatch with a wildcard.
3. Create a separate permissions stack, suggested name `alphawalk-github-publishing`, from `github-publish-role.json`. Review its change set and acknowledge `CAPABILITY_NAMED_IAM`. It creates only `alphawalk-github-deploy` with an inline policy. Do not replace or recreate the existing website stack.
4. Before merging the first main commit, disable automatic builds for the specifically identified old website app/branch so the same repository push does not also publish to old hosting. Keep shared provider or GitHub integrations used by other projects intact. The new workflow never needs the old app or account.
5. Commit the corrected `email-submit.js`, the migration infrastructure sources, and the files listed above together. The frontend must already contain the complete new API URL; the workflow deliberately refuses an old endpoint instead of rewriting source at deployment time.
6. Merge to main and inspect the Actions run. A successful first run, including AWS identity, uploads, invalidation, and HTTPS/API verification, completes activation. Subsequent website changes follow the same path. You may also select **Run workflow** on main.

The role and provider are scoped to this repository/main subject. Do not add a GitHub `environment:` to the deployment job without intentionally revisiting the trust policy; environments change the subject format.

## What a run does

**Pull requests:** only JavaScript syntax and local package/configuration checks. The validation job has `contents: read`, no `id-token: write`, and no AWS credentials. There is no `pull_request_target` workflow.

**Main pushes and manual main runs:** validation must pass first. The job checks that the triggering commit is still current main, then obtains a 30-minute AWS session through OIDC. The action rejects credentials for any other account; the script additionally verifies the exact assumed-role name.

The publisher copies only allowlisted files into a temporary staging directory, rejects symlinks and unsafe paths, and verifies that the committed IAM object list exactly matches the upload list. It uploads resources before pages and `index.html` last. HTML/JavaScript/CSS use `Cache-Control: no-cache`; images and fonts use `public, max-age=86400`. Each upload is checked with its SHA-256 checksum, content length, content type, and cache header.

It invalidates the 19 file paths plus `/` and waits for completion. It then compares all 19 files over the canonical HTTPS website to the local bytes, checks the homepage and subscription script on www and the default CloudFront hostname, and validates CORS for all three origins. One deliberately invalid email request checks the new API's 400 response without creating a subscriber. The job summary records the revision, file count, and invalidation ID.

Deployments are serialized and an active publication is not cancelled by a later push. The process is an ordered static-file update, not an atomic site swap. If it fails after some uploads, inspect the log and publish the corrected current main revision. To roll back content, create a revert commit on main; replaying an older run is intentionally blocked by the current-main check.

## Minimum AWS permissions

The role can only:

- `s3:GetObject` and `s3:PutObject` on the **19 explicitly listed object ARNs** in the website bucket.
- `cloudfront:CreateInvalidation` and `cloudfront:GetInvalidation` on distribution `E8NOVXBQ9GKY6` in the new account.

It has no bucket listing, object deletion, ACL, tagging, CloudFormation, IAM, DynamoDB, DNS, Lambda, API Gateway, or old-account permissions. AWS `GetCallerIdentity` is used to verify the session; it does not require granting an additional IAM action.

The job does not use `aws s3 sync`, `--delete`, or a repository-root upload. README files, `.git`, `infrastructure/`, scripts, credentials, and backups are excluded. Uploaded files remain governed by the existing S3 versioning and retention settings.

## Normal maintenance

- For edits to an existing static file, commit it to main through the usual review process.
- To add a new published file, add it to `website-files.txt` and add the exact matching S3 object ARN to `github-publish-role.json`. Review and apply the permission-stack update before allowing the first upload. Existing obsolete objects are not deleted automatically.
- If the API changes, update both the frontend and `deploy-config.json` to the complete `SubscriptionApiUrl` output. Do not add the old `/prod` prefix.
- Keep bucket, distribution, role ARN, and account values consistent across configuration, workflow, and the manually managed permissions stack.
- Treat action upgrades as reviewed source changes. Both third-party actions are pinned to full commit SHAs, with their release versions in comments.

Local checks require Python 3.12+ and Node.js:

```bash
node --check email-submit.js
python3 scripts/deploy_website.py validate
```

`validate` makes no network or AWS calls. `verify` only checks HTTPS and sends the described invalid API request; it does not upload files. `deploy` is restricted to the expected GitHub Actions main context and the dedicated assumed role.

## Official references

Verified on 2026-10-28:

- [GitHub OIDC claims and immutable subjects](https://docs.github.com/en/actions/reference/security/oidc)
- [GitHub OIDC configuration for AWS](https://docs.github.com/en/actions/how-tos/secure-your-work/security-harden-deployments/oidc-in-aws)
- [GitHub OIDC settings REST API](https://docs.github.com/en/rest/actions/oidc?apiVersion=2026-03-10)
- [checkout v7.0.1](https://github.com/actions/checkout/releases/tag/v7.0.1), commit `3d3c42e5aac5ba805825da76410c181273ba90b1`
- [configure-aws-credentials v6.3.0](https://github.com/aws-actions/configure-aws-credentials/releases/tag/v6.3.0), commit `e1253824e5c10ff9df46874f81ed3ec929e19cfd`
- [Ubuntu 24.04 runner image tools](https://github.com/actions/runner-images/blob/main/images/ubuntu/Ubuntu2404-Readme.md)
- [S3 PutObject](https://docs.aws.amazon.com/AmazonS3/latest/API/API_PutObject.html), [HeadObject](https://docs.aws.amazon.com/AmazonS3/latest/API/API_HeadObject.html)
- [CloudFront action/resource permissions](https://docs.aws.amazon.com/service-authorization/latest/reference/list_cloudfront.html)
- [STS GetCallerIdentity](https://docs.aws.amazon.com/STS/latest/APIReference/API_GetCallerIdentity.html)
