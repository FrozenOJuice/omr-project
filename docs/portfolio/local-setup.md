# Local setup notes

Use Git, Docker with Compose v2, Make, and a compatible shell. Windows setup uses
Git Bash. The root README contains the normal start/stop and test targets.
Canvas is optional and has its own [setup guide](../../tools/canvas/README.md).

## Prepare the development environment

1. Run `make setup-dev` to copy `app/.env.dev.example` if needed.
2. Replace the bracketed PostgreSQL/JWT/Canvas placeholders in `app/.env.dev`.
   Use matching PostgreSQL credentials in both database URLs; keep
   `TEST_DATABASE_URL` pointed at `db_test:5432/capstone_test`.
3. Keep `EMAIL_CONSOLE_MODE=true` for a demonstration. The example Resend value
   is a placeholder; console mode does not send email. Do not use real records.
4. Provision Garage below, then put its generated S3 credentials into `.env.dev`.
5. Run `make dev` to build and start the services, then `make check-dev`.
6. Run `make dev-seed` to populate the demonstration data. It fabricates large
   analytics datasets and sends a subset of generated scans through the real OMR
   pipeline. Open `http://localhost:4200` and `http://localhost:8000/docs`.

The environment validator checks nonempty values, not whether a bracketed example
has been replaced or whether a credential works. Review the completed file before
starting. Finished environment files are ignored by Git.

## Garage bootstrap for a new, disposable installation

The checked-in Garage credentials are public, disposable local defaults,
confirmed by the project maintainer. They are not deployment credentials. The
main application uses a separate S3 key and bucket supplied in `.env.dev`.

Run the following from `app/`, after completing the database/JWT settings:

```sh
docker compose --env-file .env.dev -f docker-compose.yml -f docker-compose.dev.yml up -d garage-store
docker compose --env-file .env.dev -f docker-compose.yml -f docker-compose.dev.yml exec garage-store /garage status
```

For an **unconfigured new node**, take its node ID from the status output and
replace `NODE_ID` below. Do not apply this initialization to an existing cluster
that already has a layout or data.

```sh
docker compose --env-file .env.dev -f docker-compose.yml -f docker-compose.dev.yml exec garage-store /garage layout assign -z local -c 1G NODE_ID
docker compose --env-file .env.dev -f docker-compose.yml -f docker-compose.dev.yml exec garage-store /garage layout apply --version 1
docker compose --env-file .env.dev -f docker-compose.yml -f docker-compose.dev.yml exec garage-store /garage bucket create capstone-storage
docker compose --env-file .env.dev -f docker-compose.yml -f docker-compose.dev.yml exec garage-store /garage key create local-development
docker compose --env-file .env.dev -f docker-compose.yml -f docker-compose.dev.yml exec garage-store /garage bucket allow --read --write --owner capstone-storage --key local-development
```

Store the generated key ID and secret in `GARAGE_ACCESS_KEY_ID` and
`GARAGE_SECRET_ACCESS_KEY` in `.env.dev`. Match `GARAGE_BUCKET_NAME` to the bucket.
Keep the internal endpoint `http://garage-store:3900` and browser endpoint
`http://localhost:3900`. Do not paste generated credentials into documentation.
The CLI syntax above was checked against the pinned Garage 2.3.0 image; a full
fresh-install application startup was not performed during portfolio preparation.

## Demonstration and tests

After the OMR environment and optional local Canvas stack have been built and
initialized, use [the presentation guide](../../PRESENTATION.md). Its
`presentation-up` target assumes those prerequisites; it is not a first-install
bootstrap. The invitation student uses a reserved example email, so inspect the
console link rather than sending real mail.

Read [testing precautions](testing.md) before running backend tests. Reset and
retention commands in the original guide are destructive and are unnecessary for
viewing portfolio screenshots.

## Deployment status

This portfolio uses screenshots and technical explanations. It does not require
a public deployment. The retained production Compose configuration still needs
site-specific Garage configuration/data mounts, private credentials, TLS, and
deployment validation. The audit also identified scan authorization and roster
identity-verification issues requiring review before hosting real student data.
Those application behaviors were not changed during portfolio preparation.
