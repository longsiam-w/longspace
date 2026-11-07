param([int]$Port=22,[string]$IdentityFile)
$ErrorActionPreference='Stop'
$ssh=Join-Path $env:WINDIR 'System32\OpenSSH\ssh.exe'
$a=@('-t','-p',"$Port",'-o','StrictHostKeyChecking=ask','-o','ConnectTimeout=15')
if($IdentityFile){$a+=@('-i',$IdentityFile)}
$command=@'
echo '=== Local TLS without SNI ==='; timeout 15 openssl s_client -connect 127.0.0.1:443 -noservername -verify_ip 8.163.121.238 -verify_return_error -brief </dev/null 2>&1; echo '=== Local TLS with explicit IP SNI ==='; timeout 15 openssl s_client -connect 127.0.0.1:443 -servername 8.163.121.238 -verify_ip 8.163.121.238 -verify_return_error -brief </dev/null 2>&1; echo '=== Public HTTPS from server ==='; curl --noproxy '*' -v --connect-timeout 8 --max-time 15 https://8.163.121.238/api/health 2>&1; echo; echo '=== TLS listener and reject rules ==='; /www/server/nginx/sbin/nginx -T 2>&1 | grep -nE 'configuration file|listen .*443|server_name|ssl_reject_handshake|ssl_verify_client|ssl_protocols|ssl_certificate '; echo '=== Relevant recent nginx errors ==='; tail -n 35 /www/wwwlogs/8.163.121.238.error.log; echo '=== Host firewall status ==='; ufw status; echo '=== Diagnostic complete; no configuration changed ==='
'@
Write-Host 'Read-only TLS diagnosis. No changes to website or certificates.'
& $ssh @a 'root@8.163.121.238' $command
exit $LASTEXITCODE
