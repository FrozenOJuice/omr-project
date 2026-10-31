package httpserver

import (
	"net/http"
	"os"
	"runtime/debug"
	"time"

	"ubco-team15/omr/internal/httpserver/handler"
	"ubco-team15/omr/internal/httpserver/middleware"
	"ubco-team15/omr/internal/sys"
)

func Start(hostname, port string) {

	//
	// Setup/Configuration
	//

	debug.SetMemoryLimit(256 << 20)

	s, err := handler.NewLocalResources("data")
	if err != nil {
		sys.Error("error getting server resources", "err", err)
		os.Exit(1)
	}
	defer s.Close()

	j := handler.NewJobRegistrar(time.Hour * 24)
	defer j.Close()

	adminKey := os.Getenv("OMR_ADMIN_KEY")
	if adminKey == "" {
		s.SetAdminKey("admin")
		sys.Warn(
			"OMR_ADMIN_KEY not set in the current environment; using default",
			"key", "admin",
		)
	} else {
		s.SetAdminKey(adminKey)
	}

	mux := http.NewServeMux()

	//
	// Developer Endpoints
	//

	mux.HandleFunc("GET /openapi.yaml", handler.OpenAPISpec)

	//
	// Core API
	//

	mux.HandleFunc("GET /health", handler.Health)

	mux.HandleFunc("POST /template/mark", handler.PostMarkingTemplate(s))
	mux.HandleFunc("DELETE /template/mark", handler.DeleteMarkingTemplate(s))
	mux.HandleFunc("POST /template/preprocess", handler.PostPreprocessingTemplate(s))
	mux.HandleFunc("DELETE /template/preprocess", handler.DeletePreprocessingTemplate(s))

	mux.HandleFunc("POST /scan/images", handler.PostScan(s))
	mux.HandleFunc("POST /scan/pdf", handler.PostScanPdfSync(s))
	mux.HandleFunc("DELETE /scan", handler.DeleteScans(s))

	mux.HandleFunc("GET /job", j.Handler())
	mux.HandleFunc("GET /jobs", j.ListHandler(s))
	mux.HandleFunc("GET /job/result", j.ResultHandler())
	mux.HandleFunc("POST /job/scan/pdf", j.Job(handler.PostScanPdf(s)))

	mux.HandleFunc("POST /mark", handler.PostMarkingJob(s))

	mux.HandleFunc("GET /image/snippet", handler.GetSnippet(s))
	mux.HandleFunc("GET /image", handler.GetImage(s))

	mux.HandleFunc("GET /system/utilization", handler.GetResourceUtilization(s))
	mux.HandleFunc("GET /system/logs", handler.GetLogs(s))
	mux.HandleFunc("GET /system/cpu", handler.GetCpuInfo(s))
	mux.HandleFunc("GET /system/memory", handler.GetMemoryInfo(s))

	mux.HandleFunc("GET /admin/authenticated", handler.CheckAdminKey(s))

	//
	// Deprecated endpoints
	//

	mux.HandleFunc("POST /scan", handler.PostScan(s))
	mux.HandleFunc("GET /snippet", handler.GetSnippet(s))

	//
	// Static Pages
	//

	mux.Handle("GET /", http.FileServer(http.Dir("./pages")))

	//
	// Middleware
	//

	httpHandler := middleware.Cors(mux)
	httpHandler = middleware.Recovery(httpHandler)
	httpHandler = middleware.Logger(httpHandler)

	//
	// Serve!
	//

	server := &http.Server{
		Addr:    ":" + port,
		Handler: httpHandler,
	}

	sys.Info("starting server at http://" + hostname + ":" + port)
	sys.Info(
		"monitor system usage at " +
			"http://" + hostname + ":" + port + "/dashboard.html",
	)
	server.ListenAndServe()
}
