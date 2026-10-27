# OCI 인스턴스에 GitHub Actions Self-hosted Runner 설치 가이드

Self-hosted Runner를 OCI 인스턴스에 직접 설치하면 SSH 키, Bastion, Container Registry 없이도 자동 배포가 가능하다.

---

## 전제 조건

- OCI 인스턴스가 실행 중이고 SSH 접속 가능한 상태
- 인스턴스에 Docker Engine 및 Docker Compose plugin이 설치되어 있어야 함
- GitHub Actions `deploy` job이 OCI 인스턴스에서 직접 `docker compose build/up`를 실행함
- GitHub 저장소에 대한 Admin 권한 보유

---

## 1. OCI 인스턴스에 Docker Engine 및 Compose Plugin 설치

```bash
# Ubuntu 기준
sudo apt-get update
sudo apt-get install -y ca-certificates curl gnupg

sudo install -m 0755 -d /etc/apt/keyrings
curl -fsSL https://download.docker.com/linux/ubuntu/gpg | sudo gpg --dearmor -o /etc/apt/keyrings/docker.gpg
sudo chmod a+r /etc/apt/keyrings/docker.gpg

echo \
  "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.gpg] https://download.docker.com/linux/ubuntu \
  $(. /etc/os-release && echo "$VERSION_CODENAME") stable" | \
  sudo tee /etc/apt/sources.list.d/docker.list > /dev/null

sudo apt-get update
sudo apt-get install -y docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin

# 현재 사용자를 docker 그룹에 추가 (sudo 없이 docker 사용)
sudo usermod -aG docker $USER
newgrp docker

# 설치 확인
docker --version
docker compose version
docker run --rm hello-world
```

---

## 2. GitHub Actions Self-hosted Runner 설치

### 2-1. GitHub 저장소에서 Runner 등록 토큰 발급

1. GitHub 저장소 → **Settings** → **Actions** → **Runners**
2. **New self-hosted runner** 클릭
3. OS: **Linux**, Architecture: **arm64** 선택
4. 화면에 표시된 명령어를 그대로 OCI 인스턴스에서 실행

### 2-2. Runner 다운로드 및 설치

```bash
mkdir -p ~/actions-runner && cd ~/actions-runner

# GitHub에서 제공한 최신 버전으로 교체
curl -o actions-runner-linux-x64-2.x.x.tar.gz -L \
  https://github.com/actions/runner/releases/download/v2.x.x/actions-runner-linux-x64-2.x.x.tar.gz

tar xzf ./actions-runner-linux-x64-2.x.x.tar.gz
```

### 2-3. Runner 구성 (configure)

```bash
# GitHub 저장소 페이지에서 제공한 토큰을 사용
./config.sh --url https://github.com/<owner>/<repo> --token <RUNNER_TOKEN>
```

프롬프트 응답:
- Runner group: 기본값 엔터
- Runner name: 원하는 이름 (예: `oci-instance-1`)
- Additional labels: 기본값 엔터
- Work folder: 기본값 엔터

### 2-4. Runner를 systemd 서비스로 등록 (재시작 후에도 자동 실행)

```bash
sudo ./svc.sh install
sudo ./svc.sh start

# 상태 확인
sudo ./svc.sh status
```

---

## 3. OCI 보안 그룹(Security List) 설정

인스턴스의 Ingress Rule에 다음 포트를 허용해야 한다:

| 포트 | 프로토콜 | 용도 |
|------|----------|------|
| 80   | TCP      | HTTP (Let's Encrypt ACME challenge, HTTPS 리다이렉트) |
| 443  | TCP      | HTTPS |

OCI Console → Networking → Virtual Cloud Networks → 해당 VCN → Security Lists → Ingress Rules 추가

---

## 4. Let's Encrypt 인증서 발급 및 자동 갱신

이 문서는 Ubuntu의 apt 패키지로 설치한 Certbot과 `standalone` 인증 방식을 기준으로 한다.
자동 갱신은 **`certbot.timer` → `certbot.service` → nginx 중지/시작 hook**으로 처리한다.
standalone은 80번 포트를 직접 사용하므로, 갱신 시도 중에는 nginx가 잠시 중지된다.
갱신할 필요가 없는 일반적인 실행에서는 pre/post hook을 실행하지 않는다.

실제 운영 도메인, 서버 IP/호스트명, 계정명, 인증서 일련번호, 토큰, webhook URL은 문서에 기록하지 않는다.
아래 `<your-domain>`, `<cert-name>`, `/absolute/path/to/gifttax`는 서버의 실제 값으로 바꾼다.
인증서 이름은 `sudo certbot certificates`의 `Certificate Name`을 사용한다.
기본값은 도메인이지만 `-0001` 등의 접미사가 있을 수 있다.
이 구성에서는 `CERT_DOMAIN`도 `/etc/letsencrypt/live/` 아래의 인증서 디렉토리 이름과 일치해야 한다.

### 4-1. 서버 환경변수 파일 생성

공개 저장소에는 `.env.deploy.example`만 두고, 실제 값은 서버에서 관리한다.
인증서 발급 후 컨테이너를 시작할 때 필요하므로 먼저 생성한다.

```bash
sudo mkdir -p /etc/gifttax
sudo tee /etc/gifttax/gifttax.env > /dev/null <<'EOF'
CERT_DOMAIN=<cert-name>
LETSENCRYPT_DIR=/etc/letsencrypt
EOF
```

이 파일은 runner 계정이 읽을 수 있도록 권한을 관리한다.
`deploy.yml`과 운영 명령은 `docker compose --env-file /etc/gifttax/gifttax.env ...` 형식을 사용한다.
관리자 기능을 사용하려면 기존 파일에 [관리자 필수 설정](ADMIN_AUTH.md#필수-설정)을 추가하고
[배포 점검표](RELEASE_CHECKLIST.md)를 따른다. 위 생성 예시로 기존 환경 파일을 덮어쓰지 않는다.

`docker-compose.yml`은 호스트의 `/etc/letsencrypt` 전체를 nginx에 읽기 전용으로 연결한다.
`live`의 인증서 심볼릭 링크가 가리키는 `archive`도 함께 필요하다.

```yaml
services:
  nginx:
    environment:
      CERT_DOMAIN: ${CERT_DOMAIN}
    volumes:
      - ./nginx/default.conf.template:/etc/nginx/templates/default.conf.template:ro
      - ${LETSENCRYPT_DIR:-/etc/letsencrypt}:/etc/letsencrypt:ro
      - letsencrypt-www:/var/www/certbot
```

`LETSENCRYPT_DIR`을 바꿨다면 Certbot이 실제로 관리하는 디렉토리와 동일한지 확인한다.
이하 Certbot 명령과 hook 경로는 기본값인 `/etc/letsencrypt` 기준이다.

### 4-2. 최초 인증서 발급

```bash
sudo apt-get install -y certbot

cd /absolute/path/to/gifttax

# nginx가 실행 중이면 중지하여 80번 포트를 비운다.
# 아래 명령은 순서대로 실행하고, 발급 실패 시에도 서비스 시작을 시도한다.
docker compose --env-file /etc/gifttax/gifttax.env stop nginx
sudo certbot certonly --standalone --cert-name <cert-name> -d <your-domain>
docker compose --env-file /etc/gifttax/gifttax.env up -d
```

최초 발급에 실패했다면 인증서가 없으므로 nginx도 시작되지 않을 수 있다.
발급 오류를 해결한 후 다시 시작한다. 정상 발급 후에는 아래 자동 갱신 hook을 등록한다.

### 4-3. nginx 중지·시작 hook 등록

먼저 checkout 디렉토리에서 `pwd -P`로 절대경로를 확인하고 `command -v docker`로 실행 파일 위치를 확인한다.
다음 두 스크립트의 `/absolute/path/to/gifttax`와 `/usr/bin/docker`를 실제 경로로 바꿔 등록한다.
`~`는 실행 계정에 따라 달라지므로 root가 실행하는 hook에 사용하지 않는다.

```bash
sudo mkdir -p /etc/letsencrypt/renewal-hooks/{pre,post}

sudo tee /etc/letsencrypt/renewal-hooks/pre/gifttax-nginx.sh > /dev/null <<'EOF'
#!/bin/sh
set -eu
cd "/absolute/path/to/gifttax"
/usr/bin/docker compose --env-file /etc/gifttax/gifttax.env stop nginx
EOF

sudo tee /etc/letsencrypt/renewal-hooks/post/gifttax-nginx.sh > /dev/null <<'EOF'
#!/bin/sh
set -eu
cd "/absolute/path/to/gifttax"
/usr/bin/docker compose --env-file /etc/gifttax/gifttax.env start nginx
EOF

sudo chmod 755 \
  /etc/letsencrypt/renewal-hooks/pre/gifttax-nginx.sh \
  /etc/letsencrypt/renewal-hooks/post/gifttax-nginx.sh
```

pre hook은 갱신 시도 전에 nginx를 중지하고, post hook은 갱신 시도가 실패해도 nginx 시작을 시도한다.
`start nginx`는 기존 컨테이너를 시작한다. 컨테이너가 삭제된 상태라면 4-6의 복구 명령으로 다시 생성해야 한다.
서비스 재개를 성공 시에만 실행되는 deploy hook에만 맡기지 않는다.
전원 종료나 강제 종료처럼 post hook 자체가 실행될 수 없는 경우까지 복구를 보장하는 것은 아니다.
이 디렉토리의 hook은 다른 인증서의 갱신에도 적용되므로, 인증서를 추가할 때 영향을 확인한다.

근거: [Certbot 갱신 및 hook 공식 문서](https://eff-certbot.readthedocs.io/en/stable/using.html#renewing-certificates)

### 4-4. 자동 실행 상태 확인

설정 변경 전에 기존 상태와 실행 기록부터 확인한다.
패키지 설치 시 타이머가 이미 활성화돼 있을 수 있으므로, 갱신 실패를 타이머 미실행으로 단정하지 않는다.

```bash
systemctl is-enabled certbot.timer
systemctl is-active certbot.timer
systemctl list-timers --all certbot.timer
sudo journalctl -u certbot.timer --no-pager
sudo journalctl -u certbot.service -n 100 --no-pager
```

| 확인 항목 | 의미 |
|---|---|
| `is-enabled`의 `enabled` | 부팅 시 자동 시작하도록 설정됨 |
| `is-active`의 `active` | 현재 타이머가 동작 중 |
| `list-timers`의 `NEXT` / `LAST` | 다음 예약 시각 / 마지막 실행 시각 |
| `certbot.timer` journal | 타이머 시작·중지 이력 |
| `certbot.service` journal | 실제 갱신 실행과 성공·실패 기록 |

`list-timers`에 일정이 있어도 갱신 성공을 의미하지는 않는다.
현재 상태만으로 과거 활성화 여부를 알 수 없으므로 이전 journal도 함께 확인한다.
타이머가 비활성 상태일 때 다음 명령을 실행한다.

```bash
sudo systemctl enable --now certbot.timer
```

`enable`은 부팅 시 자동 시작을 설정하고, `--now`는 지금 타이머를 시작한다.
이 명령 자체가 인증서를 즉시 갱신하는 것은 아니다.
이미 활성화된 타이머에 실행해도 별도의 중복 타이머가 생기지 않는다.
실제 실행 주기는 `systemctl cat certbot.timer`로 확인한다.

### 4-5. 만료일 확인, 수동 갱신 및 dry run

로컬 인증서 파일의 만료일을 확인한다.

```bash
sudo certbot certificates
sudo openssl x509 \
  -in /etc/letsencrypt/live/<cert-name>/fullchain.pem \
  -noout -subject -issuer -dates
```

실제 서비스가 제공하는 인증서와 HTTPS 응답도 외부 PC에서 확인한다.
서버 내부에서만 확인하면 외부 DNS·방화벽 문제를 놓칠 수 있다.

```bash
openssl s_client -connect <your-domain>:443 -servername <your-domain> </dev/null 2>/dev/null | \
  openssl x509 -noout -subject -issuer -dates
curl --fail --show-error https://<your-domain>/api/health
```

이미 만료됐거나 갱신이 필요한 인증서는 **hook 등록 후** 다음 명령으로 갱신한다.
nginx 중지·시작은 hook이 처리하므로 별도로 수동 중지하지 않는다.

```bash
sudo certbot renew --cert-name <cert-name>
sudo certbot certificates
curl --fail --show-error https://<your-domain>/api/health
```

`all renewals succeeded`, 새 만료일, `{"status":"ok"}` 응답을 함께 확인한다.
갱신할 필요가 없는 인증서는 `renew`가 성공 종료해도 만료일이 바뀌지 않을 수 있다.
복구 목적으로 `--force-renewal`을 반복하지 않는다.

설정 변경 후에는 dry run으로 갱신 절차를 시험한다. **시험 중에도 nginx가 잠시 중지된다.**

```bash
sudo certbot renew --cert-name <cert-name> --dry-run
curl --fail --show-error https://<your-domain>/api/health
```

dry run은 테스트 서버에서 인증 절차를 시험하며 운영 인증서를 교체하지 않는다.
pre/post hook도 실행되므로 `nginx 중지 → 테스트 갱신 → nginx 시작`이 동작해야 한다.
`all simulated renewals succeeded`와 시험 후 HTTPS 정상 응답을 확인한다.
직접 실행한 dry run은 예약 실행 여부를 증명하지 않으므로 타이머 상태도 별도로 확인한다.

다음처럼 출력돼도 Docker의 진행 메시지만 있다면 hook 실패를 의미하지 않는다.
Docker Compose가 진행 상황을 표준 오류(stderr)에 출력하기 때문이다.

```text
Hook 'pre-hook' ran with error output:
 Container <nginx-container> Stopping
 Container <nginx-container> Stopped
```

`Starting / Started`도 같은 의미다. 실제 오류 내용, 갱신 결과, 컨테이너 상태를 함께 판단한다.

### 4-6. 다음 갱신 실패 시 확인 순서

1. `certbot certificates`와 외부 HTTPS 인증서를 비교한다. 파일도 만료됐는지, 파일만 갱신됐는지 구분한다.
2. `list-timers`에서 다음 일정과 마지막 실행을 확인하고 `certbot.service` 로그에서 실제 실패 이유를 찾는다.
3. hook 파일의 경로·실행 권한, Docker 상태, 80번 포트 점유를 확인한다.
4. 원인을 수정한 뒤 4-5의 수동 갱신 또는 dry run을 수행하고 HTTPS 응답을 다시 확인한다.

```bash
timedatectl
systemctl list-timers --all certbot.timer
sudo journalctl -u certbot.timer -u certbot.service --since '7 days ago' --no-pager
sudo tail -n 100 /var/log/letsencrypt/letsencrypt.log
sudo ls -l /etc/letsencrypt/renewal-hooks/pre/ /etc/letsencrypt/renewal-hooks/post/
sudo cat /etc/letsencrypt/renewal-hooks/pre/gifttax-nginx.sh
sudo cat /etc/letsencrypt/renewal-hooks/post/gifttax-nginx.sh
sudo systemctl status docker --no-pager
sudo ss -ltnp 'sport = :80'

cd /absolute/path/to/gifttax
docker compose --env-file /etc/gifttax/gifttax.env ps -a
docker compose --env-file /etc/gifttax/gifttax.env logs --tail=100 nginx
```

| 증상 | 확인 및 조치 |
|---|---|
| `Could not bind TCP port 80` | standalone이 포트를 확보하지 못함. pre hook 실행 여부와 실제 점유 프로세스 확인. 다른 웹 서버라면 해당 구성도 점검 |
| `can't cd` / Compose 파일을 찾지 못함 | hook의 절대경로가 현재 checkout 경로인지 확인. 배포 디렉토리를 옮겼다면 두 hook 모두 수정 |
| `permission denied` / `docker: not found` | hook 실행 권한과 Docker 절대경로 확인 |
| ACME 연결 시간 초과 / challenge 실패 | 도메인의 A·AAAA 레코드, 공인 IP, OCI 보안 규칙과 호스트 방화벽의 80번 포트 인바운드 허용 확인 |
| 파일은 갱신됐지만 외부 인증서는 만료 | 인증서 mount, `CERT_DOMAIN`, post hook 실행 여부 확인 후 nginx 재시작. 앞단 프록시가 있다면 그 인증서도 확인 |
| nginx가 중지돼 있거나 컨테이너가 없음 | 아래 복구 명령 실행 후 nginx 로그 확인 |

```bash
cd /absolute/path/to/gifttax
# 기존 컨테이너가 중지된 경우
sudo docker compose --env-file /etc/gifttax/gifttax.env start nginx
# 컨테이너가 삭제된 경우 (앱 컨테이너는 실행 중이어야 함)
sudo docker compose --env-file /etc/gifttax/gifttax.env up -d --no-deps nginx
# 파일은 갱신됐지만 nginx가 이전 인증서를 제공하는 경우
sudo docker compose --env-file /etc/gifttax/gifttax.env restart nginx
```

필요한 복구 명령만 선택해 실행한다. 로그 공유 시 운영 도메인, IP, 계정명, 인증서 식별자와 비밀정보를 가린다.

---

## 5. 배포 디렉토리 설정

GitHub Actions self-hosted runner는 `actions/checkout` 실행 시 기본적으로 runner work 디렉토리 아래에 저장소를 checkout 한다.
예시 경로는 다음과 같다.

```bash
~/actions-runner/_work/gifttax/gifttax
```

`deploy.yml`의 `deploy` job은 `actions/checkout`으로 코드를 가져온 후  
동일 디렉토리에서 `docker compose` 명령을 실행하므로 별도 설정 불필요.

필요하면 아래 명령으로 실제 경로를 확인할 수 있다.

```bash
cd ~/actions-runner/_work/gifttax/gifttax
pwd
docker compose --env-file /etc/gifttax/gifttax.env config
```

---

## 6. 초기 배포 실행

```bash
# 인스턴스에서 최초 1회 수동으로 컨테이너 시작
cd ~/actions-runner/_work/gifttax/gifttax   # checkout 경로 예시
docker compose --env-file /etc/gifttax/gifttax.env up -d --build

# 서비스 확인
curl --fail --silent http://localhost/api/health
```

이후부터는 main 브랜치에 push될 때마다 GitHub Actions가 자동으로 배포한다.
외부에서 확인할 때는 `https://<your-domain>/api/health`로 점검하면 된다.

---

## 7. Runner 제거 방법

```bash
cd ~/actions-runner
sudo ./svc.sh stop
sudo ./svc.sh uninstall
./config.sh remove --token <RUNNER_TOKEN>
```

---

## 트러블슈팅

### docker 명령 권한 오류

```
permission denied while trying to connect to the Docker daemon socket
```

Runner 서비스가 실행되는 사용자를 docker 그룹에 추가해야 한다:

```bash
sudo usermod -aG docker <runner-user>
# 서비스 재시작
sudo ./svc.sh stop && sudo ./svc.sh start
```

### Runner가 오프라인으로 표시될 때

```bash
sudo ./svc.sh status
sudo journalctl -u actions.runner.* -n 50
```

### nginx가 인증서를 찾지 못할 때

최초 실행 시 인증서가 없으면 nginx가 시작되지 않는다.  
certbot으로 인증서를 먼저 발급한 후 `docker compose --env-file /etc/gifttax/gifttax.env up`을 실행한다.
