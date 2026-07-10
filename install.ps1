# -----------------------------------------------------------------------------
# The AI OS -- one-line installer for Windows (PowerShell)
#
#   irm https://raw.githubusercontent.com/ZDStudios/AIOS/main/install.ps1 | iex
#
# Clones the repo, installs the toolchains (uv, bun, pnpm, Node), then runs
# `aios setup` to install every project's deps, build, and wire it together.
#
# Env overrides:  $env:AIOS_DIR   $env:AIOS_BRANCH   $env:AIOS_NO_SETUP=1
# -----------------------------------------------------------------------------
$ErrorActionPreference = 'Stop'

$Repo   = 'https://github.com/ZDStudios/AIOS.git'
$Dir    = if ($env:AIOS_DIR) { $env:AIOS_DIR } else { Join-Path $HOME 'AIOS' }
$Branch = if ($env:AIOS_BRANCH) { $env:AIOS_BRANCH } else { 'main' }

function C($m){ Write-Host $m -ForegroundColor Cyan }
function OK($m){ Write-Host "OK  $m" -ForegroundColor Green }
function WARN($m){ Write-Host "!   $m" -ForegroundColor Yellow }
function Have($n){ [bool](Get-Command $n -ErrorAction SilentlyContinue) }

Write-Host ""
C "  The AI OS  --  Six AI agents. One operating system."
Write-Host ""

# 0. elevation -- The AI OS gives its agents full control of this machine and wants to
#    register a start-on-boot task. Ask once, up front, rather than dying halfway
#    through a ten-minute build. Toolchains still install into the *user* profile.
$CurrentUser = [Security.Principal.WindowsIdentity]::GetCurrent()
$Principal   = New-Object Security.Principal.WindowsPrincipal($CurrentUser)
$IsAdmin     = $Principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)

if (-not $IsAdmin -and $env:AIOS_NO_ELEVATE -ne '1') {
    WARN "The AI OS agents get full control of this machine, and setup registers a boot task."
    C   "Re-launching as Administrator (decline to continue user-local only)..."
    $selfPath = $MyInvocation.MyCommand.Definition
    if ($selfPath -and (Test-Path $selfPath)) {
        try {
            $argList = @('-NoProfile', '-ExecutionPolicy', 'Bypass', '-File', ('"' + $selfPath + '"'))
            Start-Process powershell -Verb RunAs -Wait -ArgumentList $argList
            exit 0
        } catch { WARN "elevation declined - continuing without admin" }
    } else {
        # Piped from `irm | iex`: there is no file to re-launch. Carry on unelevated;
        # everything except the boot task works fine from a user shell.
        WARN "running from a pipe - cannot self-elevate. Autostart may need an admin shell."
    }
}
if ($IsAdmin) { OK "running elevated" }

# 1. prerequisites
foreach ($t in 'git') { if (-not (Have $t)) { throw "$t is required. Install Git and re-run." } }
$py = @('py','python','python3') | Where-Object { Have $_ } | Select-Object -First 1
if (-not $py) { throw "Python 3.9+ is required. Install it from https://www.python.org/downloads/ and re-run." }
OK "prerequisites: git, $py"

# 2. clone or update
if (Test-Path (Join-Path $Dir '.git')) {
  C "Updating existing install at $Dir"
  git -C $Dir pull --ff-only
} else {
  C "Cloning The AI OS -> $Dir"
  git clone --depth 1 --branch $Branch $Repo $Dir
}
Set-Location $Dir

# 3. toolchains (aios finds these even if not yet on PATH)
C "Installing toolchains..."
if (-not (Have 'uv'))   { C "* uv";   irm https://astral.sh/uv/install.ps1 | iex }
if (-not (Have 'bun'))  { C "* bun";  irm bun.sh/install.ps1 | iex }
if (-not (Have 'node')) { WARN "Node >=20 not found -- install it from https://nodejs.org (openclaw needs it)" }
if (-not (Have 'pnpm')) { C "* pnpm"; if (Have 'npm') { npm i -g pnpm } else { irm https://get.pnpm.io/install.ps1 | iex } }

# 4. run aios setup
if ($env:AIOS_NO_SETUP -eq '1') {
  OK "cloned; skipping setup (AIOS_NO_SETUP=1)"
} else {
  C "Running aios setup (installs deps, builds, wires - takes a few minutes)..."
  if ($py -eq 'py') { py -3 aios.py setup --non-interactive } else { & $py aios.py setup --non-interactive }
}

Write-Host ""
OK "The AI OS is installed at: $Dir"
Write-Host ""
C "Next steps:"
Write-Host "   cd `"$Dir`""
Write-Host "   .\aios.ps1 setup --force     # enter your model provider + API key"
Write-Host "   .\aios.ps1 start             # bring the whole stack up"
Write-Host "   .\aios.ps1 url               # open the dashboard"
Write-Host ""
