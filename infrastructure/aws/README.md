# AlphaWalk AWS deployment

`template.yaml` versions the infrastructure for the static website and email subscription API. Website files are uploaded separately; this directory does not install a deployment pipeline.

## Deployment configuration

| Setting | Value |
| --- | --- |
| CloudFormation stack | `alphawalk-website` |
| AWS Region | `us-east-1` |
| DynamoDB table parameter | `SubscribersTableName=AlphaWalkSubscribers` |
| Website domains | `alphawalk.ai`, `www.alphawalk.ai` |
| Optional certificate parameter | `WebsiteCertificateArn` |
| Alias binding switch | `EnableWebsiteAliases=true` by default |

The stack contains a private, versioned S3 bucket, a CloudFront distribution with Origin Access Control, and an HTTP API → Lambda → DynamoDB subscription service. The Lambda role has write access to its subscription table and function logs. Function and API logs are retained for 14 days.

Before creating or updating the stack, verify the active AWS account, validate the template, and review the CloudFormation change set. Creating the execution role requires `CAPABILITY_IAM`. Keep credentials, private configuration, and account-specific deployment state out of the public repository. The public subscription endpoint belongs in the frontend configuration.

## Deploy first with the temporary hostname

1. Create the stack with `WebsiteCertificateArn` empty and `SubscribersTableName` set to `AlphaWalkSubscribers`. The named table must not already exist outside this stack.
2. Wait for the stack to complete and retrieve its outputs:

   ```bash
   aws cloudformation describe-stacks \
     --stack-name alphawalk-website \
     --region us-east-1 \
     --query 'Stacks[0].Outputs' \
     --output table
   ```

3. Use `WebsiteUrl` for the temporary HTTPS site, `WebsiteBucketName` for uploads, and `SubscriptionApiUrl` for the frontend subscription request.
4. Upload the reviewed website files, then verify the page, static assets, browser CORS behavior, and a test subscription in the new DynamoDB table. Repeat submission of the same email should succeed without replacing its original creation time.

The API uses the `$default` stage. **Use the complete `SubscriptionApiUrl` output exactly as returned; do not append or retain the old `/prod` prefix.** The request is `POST` with `Content-Type: application/json` and a body such as `{"email":"person@example.com"}`.

## Add the official domains

1. Prepare an issued ACM certificate in `us-east-1` covering both `alphawalk.ai` and `www.alphawalk.ai`. Keep its DNS validation records in place. A certificate covering only `api.alphawalk.ai` is insufficient.
2. Confirm that the domain aliases can be associated with the target distribution. Empty DNS records do not prove that an old CloudFront distribution has released its aliases. If a cross-account transfer is needed, first set `WebsiteCertificateArn` to the new certificate and `EnableWebsiteAliases=false`. This attaches the certificate without trying to claim the aliases. Follow AWS's domain transfer procedure, including DNS ownership verification and the source distribution requirements.
3. After resolving any existing association, update the same stack with the website certificate ARN and `EnableWebsiteAliases=true`. Preserve the table name. This enables both aliases, SNI, and `TLSv1.2_2021`; leaving the certificate parameter empty uses only the default CloudFront certificate.
4. After the distribution is deployed, configure the authoritative Route 53 records for both names to point to the distribution. Use A and AAAA alias records because IPv6 is enabled. The template does not create certificates or DNS records.
5. Verify HTTPS, page assets, and subscriptions through the official domains.

## Update the frontend

- Prepare a separate upload directory from a known source commit. Use an explicit file allowlist: `index.html`, `email-submit.js` if referenced, and the actual additional HTML, CSS, JavaScript, images, fonts, and other static assets required by the site.
- Exclude `README` files, `.git`, `infrastructure/`, credentials, environment files, development tools, and historical backups. **Do not sync the repository root directly to S3.**
- Update every active subscription request to the current complete `SubscriptionApiUrl`. Check both inline handlers and external scripts, and ensure one form submission sends one request.
- Upload with correct content types. Use `Cache-Control: no-cache` for HTML and JavaScript whose filenames do not contain a content hash. The CloudFront policy has a minimum TTL of zero so origin cache directives can take effect.
- Use `CloudFrontDistributionId` to invalidate changed paths when needed. Confirm the updated page calls the new API before publishing the corresponding source change. Do not use broad object deletion unless the exact removal list has been reviewed.

## Data and resource retention

S3 and DynamoDB have `DeletionPolicy: Retain` and `UpdateReplacePolicy: Retain`. Deleting the stack leaves the bucket, its object versions, and the subscription table in place; the distribution, API, function, role, and log groups are removed. DynamoDB deletion protection is also enabled.

Changing `SubscribersTableName` replaces the table; it is not an in-place rename and does not copy data. Keep the existing value during normal updates. Retained resources and S3 object versions require separate management and may continue to incur charges.

**Historical subscribers from the old AWS account have not been migrated by this template.** Any data transfer must be handled and verified separately. The new endpoint records subscriptions in the new table; it does not send emails.

## Automatic website publishing

For the separate GitHub OIDC publishing role, workflow setup, and ongoing static-site releases, see [AUTOMATION.md](AUTOMATION.md). Infrastructure changes remain manually managed through CloudFormation.
