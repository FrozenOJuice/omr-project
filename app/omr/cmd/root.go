package cmd

import (
	"os"

	"github.com/spf13/cobra"
)

var rootCmd = &cobra.Command{
	Use:   "omr",
	Short: "An Optical Mark Recognition (OMR) service exposed via HTTP",
	Long:  `An Optical Mark Recognition (OMR) service exposed via HTTP.`,
}

func Execute() {
	err := rootCmd.Execute()
	if err != nil {
		os.Exit(1)
	}
}
