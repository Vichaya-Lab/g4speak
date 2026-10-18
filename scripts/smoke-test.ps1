param(
    [string]$Installer = (Join-Path $PSScriptRoot '..\dist\G4Speak-Setup-1.2.2.exe'),
    [string]$PreviousInstaller = '',
    [string]$PreviousVersion = '1.2.1'
)
$ErrorActionPreference = 'Stop'
$Installer = (Resolve-Path -LiteralPath $Installer).Path
$initialInstaller = if ($PreviousInstaller) { (Resolve-Path -LiteralPath $PreviousInstaller).Path } else { $Installer }
$initialVersion = if ($PreviousInstaller) { $PreviousVersion } else { '1.2.2' }
$uninstallKey = 'HKCU:\Software\Microsoft\Windows\CurrentVersion\Uninstall\{B3F29956-3D69-4994-9B8D-84317FD5C621}_is1'
if (Test-Path -LiteralPath $uninstallKey) {
    throw 'G4Speak is already installed for this user. Run this isolated installer test on a clean account.'
}
$testRoot = Join-Path ([IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..\build'))) ('installer-smoke-' + [guid]::NewGuid().ToString('N'))
$installDirectory = Join-Path $testRoot 'app'
New-Item -ItemType Directory -Path $testRoot -Force | Out-Null

function Invoke-CheckedProcess([string]$File, [string[]]$Arguments) {
    $process = Start-Process -FilePath $File -ArgumentList $Arguments -WindowStyle Hidden -PassThru
    if (-not $process.WaitForExit(120000)) {
        $process.Kill()
        throw "Installer smoke test process timed out: $File"
    }
    if ($process.ExitCode -ne 0) { throw "Installer smoke test failed: $File (exit $($process.ExitCode))." }
}

$installArguments = @('/VERYSILENT', '/SUPPRESSMSGBOXES', '/NORESTART', '/NOICONS', '/TASKS=""', ('/DIR="' + $installDirectory + '"'))
$executable = Join-Path $installDirectory 'G4Speak.exe'
$uninstaller = Join-Path $installDirectory 'unins000.exe'
$dictionary = Join-Path $env:APPDATA 'G4Speak\dictionary.json'
$dictionaryHash = if (Test-Path -LiteralPath $dictionary) { (Get-FileHash -LiteralPath $dictionary).Hash } else { $null }
try {
    Invoke-CheckedProcess $initialInstaller ($installArguments + @('/LOG="' + (Join-Path $testRoot 'install.log') + '"'))
    if (-not (Test-Path -LiteralPath $executable) -or -not (Test-Path -LiteralPath $uninstaller)) {
        throw 'Setup did not install the app and uninstaller.'
    }
    $installedVersion = (Get-ItemProperty -LiteralPath $uninstallKey).DisplayVersion
    if ($installedVersion -ne $initialVersion) {
        throw "Expected installed version '$initialVersion', got '$installedVersion'."
    }
    Invoke-CheckedProcess $executable @('--smoke-test')
    $settings = Join-Path $installDirectory '.env'
    'GROQ_API_KEY=installer-upgrade-test-placeholder' | Set-Content -LiteralPath $settings -Encoding ascii
    $settingsHash = (Get-FileHash -LiteralPath $settings).Hash
    Invoke-CheckedProcess $Installer ($installArguments + @('/LOG="' + (Join-Path $testRoot 'upgrade.log') + '"'))
    if ((Get-ItemProperty -LiteralPath $uninstallKey).DisplayVersion -ne '1.2.2') {
        throw 'Upgrade did not register the new version.'
    }
    if ((Get-FileHash -LiteralPath $settings).Hash -ne $settingsHash) { throw 'Upgrade changed the existing API settings.' }
    Invoke-CheckedProcess $executable @('--smoke-test')
} finally {
    if (Test-Path -LiteralPath $uninstaller) {
        Invoke-CheckedProcess $uninstaller @('/VERYSILENT', '/SUPPRESSMSGBOXES', '/NORESTART', ('/LOG="' + (Join-Path $testRoot 'uninstall.log') + '"'))
    }
}
if (Test-Path -LiteralPath $executable) { throw 'Uninstall left the application executable behind.' }
if (Test-Path -LiteralPath $uninstallKey) { throw 'Uninstall left its Windows registration behind.' }
if ((Get-FileHash -LiteralPath $settings).Hash -ne $settingsHash) { throw 'Uninstall removed or changed user API settings.' }
if ($dictionaryHash -and (Get-FileHash -LiteralPath $dictionary).Hash -ne $dictionaryHash) {
    throw 'The existing personal dictionary changed during installation testing.'
}
Write-Output 'Install, bundled app startup, upgrade, settings preservation, and uninstall passed.'
