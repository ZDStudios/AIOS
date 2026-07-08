# The AI OS launcher (PowerShell / Windows-primary).
# Usage:  .\aios.ps1 <command> [args...]     e.g.  .\aios.ps1 doctor
$ErrorActionPreference = 'Stop'
$here = Split-Path -Parent $MyInvocation.MyCommand.Path
$script = Join-Path $here 'aios.py'

function Get-Python {
    foreach ($c in @('py', 'python', 'python3')) {
        $cmd = Get-Command $c -ErrorAction SilentlyContinue
        if ($cmd) {
            if ($c -eq 'py') { return @('py', '-3') }
            return @($cmd.Source)
        }
    }
    return $null
}

$py = Get-Python
if (-not $py) {
    Write-Error "Python 3 not found. Install it from https://www.python.org/downloads/ and retry."
    exit 1
}

$argv = @($py) + @($script) + $args
& $argv[0] @($argv[1..($argv.Count - 1)])
exit $LASTEXITCODE
