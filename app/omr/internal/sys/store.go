package sys

import (
	"context"
	"database/sql"
	_ "embed"
	"testing"

	"ubco-team15/omr/internal/sys/sqlc"

	_ "modernc.org/sqlite" // sqlite3 driver
)

//
// We use SQLite3 to store certain persistent data about the system.
//
// Update (8/2/2026): The database no longer stores anything that we use, but
// I'm still going to keep it around because it might be useful later.
//

//go:embed sqlc/schema.sql
var databaseInit string

// The interface we used to interact with the SQLite3 database.
var db sqlc.Querier

// The path to the SQLite data file.
const dbPath = "data/sys.sqlite3"

func init() {

	//
	// Start up the database.
	//

	path := dbPath
	if testing.Testing() {
		path = ":memory:"
	}

	cnx, err := sql.Open("sqlite", path)
	if err != nil {
		panic("failed to open sys database")
	}

	cnx.SetMaxOpenConns(1)

	db = sqlc.New(cnx)

	ctx := context.Background()
	if _, err := cnx.ExecContext(ctx, databaseInit); err != nil {
		panic("failed to initialize sys database")
	}
}
