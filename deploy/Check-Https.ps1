param([int]$Port=22,[string]$IdentityFile)
$ErrorActionPreference='Stop'
$ssh=Join-Path $env:WINDIR 'System32\OpenSSH\ssh.exe'
$sshArgs=@('-t','-p',"$Port",'-o','StrictHostKeyChecking=ask','-o','ConnectTimeout=15')
if($IdentityFile){$sshArgs+=@('-i',$IdentityFile)}
$command=@'
echo '=== Certificate dates and IP identity ==='; openssl x509 -in /etc/letsencrypt/live/private-hub-ip/fullchain.pem -noout -issuer -subject -dates -ext subjectAltName; echo '=== Verify live TLS locally with IP identity ==='; curl --noproxy '*' --connect-to 8.163.121.238:443:127.0.0.1:443 --connect-timeout 10 --max-time 20 -i https://8.163.121.238/api/health; echo; echo '=== Actual nginx certificate paths ==='; /www/server/nginx/sbin/nginx -T 2>&1 | grep -E 'ssl_certificate|server_name 8.163.121.238'; echo '=== Renewal timer enabled ==='; systemctl is-enabled private-hub-cert-renew.timer; systemctl is-active private-hub-cert-renew.timer; systemctl list-timers private-hub-cert-renew.timer --no-pager; echo '=== Single staging renewal retry; production certificate unchanged ==='; /opt/private-hub-certbot/bin/certbot renew --cert-name private-hub-ip --dry-run --run-deploy-hooks --http-01-port 80
'@
Write-Host 'Checks certificate and HTTPS, then retries simulated renewal once. No password reset or production certificate reissue.'
& $ssh @sshArgs 'root@8.163.121.238' $command
exit $LASTEXITCODE
