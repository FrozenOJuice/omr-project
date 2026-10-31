package database

import (
	"context"
	"database/sql"
	_ "embed"
	"ubco-team15/omr/internal/database/sqlc"

	_ "modernc.org/sqlite" // sqlite3 driver
)

//go:embed sqlc/schema.sql
var databaseInit string

var initialized bool

type Querier sqlc.Querier

func initialize(db *sql.DB) error {
	ctx := context.Background()
	if _, err := db.ExecContext(ctx, databaseInit); err != nil {
		return err
	}

	initialized = true
	return nil
}

func Connect(databaseFilepath string) (Querier, *sql.DB, error) {

	db, err := sql.Open("sqlite", databaseFilepath)
	if err != nil {
		return nil, nil, err
	}

	db.SetMaxOpenConns(1)

	if err := initialize(db); err != nil {
		return nil, nil, err
	}

	return sqlc.New(db), db, nil
}
