package cmd

import (
	"fmt"
	"net"
	"strconv"
	"ubco-team15/omr/internal/httpserver"

	"github.com/spf13/cobra"
)

var portNum int

var serveCmd = &cobra.Command{
	Use:   "serve",
	Short: "Starts the OMR's HTTP server.",
	Long:  `Starts the OMR's HTTP server.`,
	PreRunE: func(cmd *cobra.Command, args []string) error {
		if portNum < 1 || portNum > 65535 {
			return fmt.Errorf(
				"invalid port %d: must be between 1 and 65535",
				portNum,
			)
		}

		testCnx, err := net.Listen("tcp", ":"+strconv.Itoa(portNum))
		if err != nil {
			return fmt.Errorf(
				"port %d is already in use.",
				portNum,
			)
		}
		testCnx.Close()

		return nil
	},
	Run: func(cmd *cobra.Command, args []string) {
		httpserver.Start("localhost", strconv.Itoa(portNum))
	},
}

func init() {
	rootCmd.AddCommand(serveCmd)

	serveCmd.Flags().IntVarP(
		&portNum,
		"port",
		"p",
		3000,
		"port to listen on (1-65535)",
	)
}
