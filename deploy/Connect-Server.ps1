param([string]$ServerHost='8.163.121.238',[string]$User,[int]$Port=22,[string]$IdentityFile)
$ErrorActionPreference='Stop'
if(-not $User){$User=Read-Host 'SSH username (provided by your server console)'}
if($User -notmatch '^[a-zA-Z0-9_.-]+$'){throw 'Invalid username'}
$ssh=Join-Path $env:WINDIR 'System32\OpenSSH\ssh.exe'
$argsList=@('-t','-p',"$Port",'-o','StrictHostKeyChecking=ask','-o','ConnectTimeout=15')
if($IdentityFile){$argsList+=@('-i',$IdentityFile)}
$argsList+="$User@$ServerHost"
Write-Host 'Verify host fingerprint against your cloud console. Password/passphrase is entered only in SSH, never in chat.'
Write-Host 'This probe is read-only. No website files or service configurations will change.'
# Use POSIX single quotes: Windows PowerShell 5.1 can strip embedded double
# quotes when invoking native executables. These single quotes reach Bash intact.
$probe = @'
echo '=== Identity / OS ==='; id; uname -a; cat /etc/os-release; echo '=== Services / listeners ==='; command -v nginx; command -v python3; command -v docker; ss -lnt; echo '=== Nginx configuration ==='; if [ $(id -u) = 0 ]; then nginx -T; else sudo nginx -T; fi; echo '=== Web roots ==='; ls -ld /var/www /usr/share/nginx/html /www/wwwroot /opt 2>/dev/null; echo '=== Probe complete ==='
'@
& $ssh @argsList $probe
exit $LASTEXITCODE
