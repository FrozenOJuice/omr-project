# OMR Service

This directory contains the source code for the OMR service.

## Setup

The docker image can be built from the top-level dockerfile. 

```sh
# from the `app/omr` directory...
docker build --tag omr_server .
```

Since we use OpenCV as a dependency the program takes a while to build. Refer to the [this section](#setting-up-a-local-environment) if you need a faster build for development. 

Once the image is built, you can run the app via docker:

```sh
docker run --rm -p 3000:3000 --name omr omr_server
```

This will log a URL to the documentation on startup. Follow that link to view details about the endpoints.

If you want the container to persist and maintain its stored data (volume), instead run:

```sh
docker run -p 3000:3000 -v omr-data:/app/data --name omr omr_server
```

### Testing

If you want to run tests in a container (named `omr` in this case), run

```sh
docker exec -t omr sh -c "go test ./..."
```

To execute coverage tests, you can run a script from inside the container:

```sh
docker exec -t omr sh -c "./scripts/coverage.sh"
```

## Setting Up a Local Environment

>The Go version set in `go.mod` is fixed to match the version of the GoCV image we rely on. Do not change it.

In order to run the project outside of Docker, you must first ensure that you have [OpenCV](https://gocv.io/getting-started/) and [Go](https://go.dev/doc/install) installed. If you have those, you should be able to run the program:

```sh
go run .
```

This should print a help message that describes the subcommands for the program. 

If you get an error that mentions missing C/C++ objects, it's likely that GoCV isn't seeing your OpenCV installation. Refer to [their documentation](https://gocv.io/getting-started/) to correct this.

## File Structure

In keeping with Go conventions, the top-level directories are as follows:
- [`cmd`](./cmd) contains the [Cobra](https://github.com/spf13/cobra) commands that serve as entrypoints to the program. The [`rootCmd`](./cmd/root.go) command is used by the top-level [`main.go`](./main.go) program.
- [`api`](./api) includes the specification(s) for the HTTP server. It does not contain the actual server code, just the specification.
- [`internal`](./internal) contains packages that are used internally. This will be most of the project.
  - [`database`](./internal/database/) contains all database interactions. Most of the queries are generated with sqlc (I explain this more [here](./internal/database/sqlc/README.md)).
  - [`httpserver`](./internal/httpserver/) contains the handler functions and middleware that make up the HTTP API for the service. We are just using the standard [`net/http`](https://pkg.go.dev/net/http) library since the API should be relatively simple.
    - [`dto`](./internal/httpserver/dto/) contains the data transfer objects (DTOs) for the server. Any complex object that will be sent or received from the server is put there, along with relevant deserialization and validation functions.
    - [`handler`](./internal/httpserver/handler/) includes the bulk of the HTTP server's logic.
  - [`fs`](./internal/fs/) exposes a simple interface for file storage, particularly images. Internally, it currently has two implementations; one wraps the local file system (suitable for testing) and the other wraps an S3 client.
  - [`pdf`](./internal/pdf) handles PDF rendering.
  - [`sys`](./internal/sys) centralizes logging and resource monitoring.

For more info about the top-level directory naming standards, refer to [this document](https://github.com/golang-standards/project-layout). This is not an "official" project setup, but it is a popular one.

## Dependencies

The following is a list of dependencies. You can also refer to the [go.mod](./go.mod) file.

C dependencies:
- [OpenCV](https://opencv.org/) is used for computer vision stuff.

Go packages (excluding the standard library):
- [GoCV](gocv.io/x/gocv) provides Go bindings for OpenCV.
- [SQLite3](modernc.org/sqlite) is included as our local database.
- [rs/cors](https://pkg.go.dev/github.com/rs/cors) is used to configure CORS. It's thinly wrapped in [cors.go](./internal/httpserver/middleware/cors.go). 
- [Cobra](https://cobra.dev/) is used to set up the command-line interface. It's only used in the [cmd](./cmd) package.
- [lz4](https://github.com/pierrec/lz4/v4) is used to compress OpenCV matrices when we save them to persistent storage.
- [pdfcpu](https://github.com/pdfcpu/pdfcpu) is used to preprocess PDFs.
- [fitz](https://github.com/gen2brain/go-fitz) is used to render PDFs.
- [gopsutil](https://github.com/shirou/gopsutil/v4) is used to make OS-agnostic syscalls for monitoring resource usage.
- [Google's UUID package](https://github.com/google/uuid) is used for generating UUIDs.

Developer dependencies (not required for runtime):
- [sqlc](https://sqlc.dev/) is used to generate Go functions from SQL queries (read more [here](./internal/database/sqlc/README.md)).