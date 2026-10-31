package cmd

import (
	"fmt"
	"runtime"

	"github.com/gen2brain/go-fitz"
	"github.com/spf13/cobra"
	"gocv.io/x/gocv"
)

const version = "0.0.1"

// versionCmd represents the version command
var versionCmd = &cobra.Command{
	Use:   "version",
	Short: "Prints the version of the service and its dependencies",
	Long:  `Prints the version of the service and its dependencies.`,
	Run: func(cmd *cobra.Command, args []string) {
		s := "\n"
		s += "  OMR version           \u001B[96m" +
			version + "\u001B[0m\n"
		s += "  ─┬─\n"
		s += fmt.Sprintf("   ├──runtime           %s\n", runtime.Version())
		s += fmt.Sprintf("   ├──gocv version      %s\n", gocv.Version())
		s += fmt.Sprintf("   ├──opencv version    %s\n", gocv.OpenCVVersion())
		s += fmt.Sprintf("   └──fitz version      %s\n", fitz.FzVersion)
		s += "\n"

		fmt.Print(s)
	},
}

func init() {
	rootCmd.AddCommand(versionCmd)
}
