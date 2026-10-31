package sys

import (
	"bufio"
	"fmt"
	"io"
	"strings"
	"time"
)

//
// This file implements general logging functionality suitable for use across
// the entire application.
//

var logCache *RingBuffer[string]

func init() {
	logCache = NewRingBuffer[string](1 << 12)
}

type level int

const (
	levelMisc level = iota
	levelInfo
	levelDebug
	levelWarn
	levelError
)

func log(level level, msg string, args ...any) {

	t := time.Now().Local().Format("2006-01-02 15:04:05.000")

	s := strings.Builder{}
	s.WriteString(t)
	s.WriteString(" ")
	switch level {
	case levelMisc:
		s.WriteString("[LOG]   ")
	case levelInfo:
		s.WriteString("[INFO]  ")
	case levelDebug:
		s.WriteString("[DEBUG] ")
	case levelWarn:
		s.WriteString("[WARN]  ")
	case levelError:
		s.WriteString("[ERROR] ")
	}
	s.WriteString(msg)

	if len(args) == 1 {
		fmt.Fprintf(&s, " -- %v", args[0])
	}
	if len(args) >= 2 {
		for i := 0; i < len(args)-1; i += 2 {
			fmt.Fprintf(&s, " -- %v: %v", args[i], args[i+1])
		}
		if len(args)%2 == 1 {
			fmt.Fprintf(&s, " -- %v", args[len(args)-1])
		}
	}

	str := s.String()

	switch level {
	case levelMisc:
		fmt.Println(FgBrightBlack(str))
		logCache.Add(str)
	case levelInfo:
		fmt.Println(FgBrightCyan(str))
		logCache.Add(str)
	case levelDebug:
		fmt.Println(FgBrightBlue(str))
		logCache.Add(str)
	case levelWarn:
		fmt.Println(FgBrightYellow(str))
		logCache.Add(str)
	case levelError:
		fmt.Println(FgBrightRed(str))
		logCache.Add(str)
	}
}

// Writes a generic log to standard output and caches it in memory.
func Log(msg string, args ...any) { log(levelMisc, msg, args...) }

// Writes an info-level log to standard output and caches it in memory.
func Info(msg string, args ...any) { log(levelInfo, msg, args...) }

// Writes a debug-level log to standard output and caches it in memory.
func Debug(msg string, args ...any) { log(levelDebug, msg, args...) }

// Writes a warn-level log to standard output and caches it in memory.
func Warn(msg string, args ...any) { log(levelWarn, msg, args...) }

// Writes a error-level log to standard output and caches it in memory. Use
// this to log unexpected behavior.
func Error(msg string, args ...any) { log(levelError, msg, args...) }

// Writes up to n of the most recent logs (delimited by newlines) to the given
// writer.
func DumpLogs(w io.Writer, n int) {
	bw := bufio.NewWriter(w)
	for _, log := range logCache.Get(n) {
		bw.WriteString(log)
		bw.WriteString("\n")
	}
	bw.Flush()
}

//
// Below we just define a bunch of ANSI constants to set terminal colors and
// stuff. We won't use many of them, but we may as well keep them here just in
// case (the code is copy+pasted from one of my other projects, in case you're
// wondering).
//

const (
	FG_BLACK   = "\u001B[30m"
	FG_RED     = "\u001B[31m"
	FG_GREEN   = "\u001B[32m"
	FG_YELLOW  = "\u001B[33m"
	FG_BLUE    = "\u001B[34m"
	FG_MAGENTA = "\u001B[35m"
	FG_CYAN    = "\u001B[36m"
	FG_WHITE   = "\u001B[37m"

	FG_BRIGHT_BLACK   = "\u001B[90m"
	FG_BRIGHT_RED     = "\u001B[91m"
	FG_BRIGHT_GREEN   = "\u001B[92m"
	FG_BRIGHT_YELLOW  = "\u001B[93m"
	FG_BRIGHT_BLUE    = "\u001B[94m"
	FG_BRIGHT_MAGENTA = "\u001B[95m"
	FG_BRIGHT_CYAN    = "\u001B[96m"
	FG_BRIGHT_WHITE   = "\u001B[97m"

	BG_BLACK   = "\u001B[40m"
	BG_RED     = "\u001B[41m"
	BG_GREEN   = "\u001B[42m"
	BG_YELLOW  = "\u001B[43m"
	BG_BLUE    = "\u001B[44m"
	BG_MAGENTA = "\u001B[45m"
	BG_CYAN    = "\u001B[46m"
	BG_WHITE   = "\u001B[47m"

	BG_BRIGHT_BLACK   = "\u001B[100m"
	BG_BRIGHT_RED     = "\u001B[101m"
	BG_BRIGHT_GREEN   = "\u001B[102m"
	BG_BRIGHT_YELLOW  = "\u001B[103m"
	BG_BRIGHT_BLUE    = "\u001B[104m"
	BG_BRIGHT_MAGENTA = "\u001B[105m"
	BG_BRIGHT_CYAN    = "\u001B[106m"
	BG_BRIGHT_WHITE   = "\u001B[107m"

	BOLD = "\u001B[1m"
	DIM  = "\u001B[2m"

	ITALIC              = "\u001B[3m"
	ITALIC_RESET        = "\u001B[23m"
	UNDERLINE           = "\u001B[4m"
	UNDERLINE_RESET     = "\u001b[24m"
	BLINK               = "\u001B[5m"
	BLINK_RESET         = "\u001b[25m"
	REVERSE             = "\u001B[7m"
	REVERSE_RESET       = "\u001b[27m"
	HIDDEN              = "\u001B[8m"
	HIDDEN_RESET        = "\u001b[28m"
	STRIKETHROUGH       = "\u001B[9m"
	STRIKETHROUGH_RESET = "\u001b[29m"

	ERASE_SCREEN              = "\u001B[2J"
	RESET_CURSOR              = "\u001B[H"
	MOVE_CURSOR_TO_LINE_START = "\u001B[1G"

	RESET           = "\u001B[0m"
	RESET_FG        = "\u001B[39m"
	RESET_BG        = "\u001b[49m"
	RESET_INTENSITY = "\u001b[22m"

	HIDE_CURSOR = "\u001B[?25l"
	SHOW_CURSOR = "\u001B[?25h"
)

// func FgBlack(s string) string   { return FG_BLACK + s + RESET_FG }
// func FgRed(s string) string     { return FG_RED + s + RESET_FG }
// func FgGreen(s string) string   { return FG_GREEN + s + RESET_FG }
// func FgYellow(s string) string  { return FG_YELLOW + s + RESET_FG }
// func FgBlue(s string) string    { return FG_BLUE + s + RESET_FG }
// func FgMagenta(s string) string { return FG_MAGENTA + s + RESET_FG }
// func FgCyan(s string) string    { return FG_CYAN + s + RESET_FG }
// func FgWhite(s string) string   { return FG_WHITE + s + RESET_FG }

func FgBrightBlack(s string) string { return FG_BRIGHT_BLACK + s + RESET_FG }
func FgBrightRed(s string) string   { return FG_BRIGHT_RED + s + RESET_FG }

// func FgBrightGreen(s string) string   { return FG_BRIGHT_GREEN + s + RESET_FG }
func FgBrightYellow(s string) string { return FG_BRIGHT_YELLOW + s + RESET_FG }
func FgBrightBlue(s string) string   { return FG_BRIGHT_BLUE + s + RESET_FG }

// func FgBrightMagenta(s string) string { return FG_BRIGHT_MAGENTA + s + RESET_FG }
func FgBrightCyan(s string) string { return FG_BRIGHT_CYAN + s + RESET_FG }

// func FgBrightWhite(s string) string   { return FG_BRIGHT_WHITE + s + RESET_FG }

// func Bold(s string) string { return BOLD + s + RESET_INTENSITY }
// func Dim(s string) string  { return DIM + s + RESET_INTENSITY }

// func Italic(s string) string        { return ITALIC + s + ITALIC_RESET }
// func Underline(s string) string     { return UNDERLINE + s + UNDERLINE_RESET }
// func Blink(s string) string         { return BLINK + s + BLINK_RESET }
// func Reverse(s string) string       { return REVERSE + s + REVERSE_RESET }
// func Hidden(s string) string        { return HIDDEN + s + HIDDEN_RESET }
// func Strikethrough(s string) string { return STRIKETHROUGH + s + STRIKETHROUGH_RESET }

func ClearScreen() { fmt.Print(ERASE_SCREEN + RESET_CURSOR) }
