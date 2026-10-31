# sqlc Source Files

This directory contains the configuration and `.sql` files for sqlc to generate typesafe Go functions to query the database.
- [schema.sql](./schema.sql) defines the database schema.
- [queries.sql](./queries.sql) defines the queries that we want to run against the database, which sqlc converts into Go functions.
- [sqlc.yaml](./sqlc.yaml) configures sqlc.

[sqlc](https://docs.sqlc.dev/en/latest/index.html) is strictly a code generation tool, it is not a runtime dependency. You can install it via go:

```sh
go install github.com/sqlc-dev/sqlc/cmd/sqlc@latest
```

Then, cd into this directory and run the following command to generate the Go code.

```sh
sqlc generate
```

You don't need to pass any additional command-line arguments; the configuration is strictly handled by the detected configuration file. You can read more about how to use sqlc [here](https://docs.sqlc.dev/en/latest/tutorials/getting-started-postgresql.html). 
