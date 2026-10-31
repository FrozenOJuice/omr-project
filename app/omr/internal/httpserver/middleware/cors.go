package middleware

import (
	"github.com/rs/cors"
)

// Middleware to configure CORS.
var Cors = cors.Default().Handler
