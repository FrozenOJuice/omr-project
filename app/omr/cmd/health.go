package cmd

import (
	"net/http"
	"os"
	"ubco-team15/omr/internal/sys"

	"github.com/spf13/cobra"
)

const port = "3000"

var healthcheckCmd = &cobra.Command{
	Use:   "health",
	Short: "Checks whether the OMR HTTP service is healthy",
	Run: func(cmd *cobra.Command, args []string) {

		resp, err := http.Get("http://localhost:" + port + "/health")
		if err != nil {
			sys.Error("health check error", "error", err)
			os.Exit(1)
		}
		defer resp.Body.Close()

		if resp.StatusCode != http.StatusOK {
			sys.Error("health check failed", "response status", resp.Status)
			os.Exit(1)
		}

		os.Exit(0)
	},
}

func init() {
	rootCmd.AddCommand(healthcheckCmd)
}
