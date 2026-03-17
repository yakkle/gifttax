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
3. OS: **Linux**, Architecture: **x64** 선택
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

## 4. Let's Encrypt SSL 인증서 발급

Runner 설치 후 최초 1회 수동으로 인증서를 발급해야 한다.
현재 문서는 `certbot standalone` 방식을 기준으로 설명한다.
이 방식은 인증서 발급 또는 갱신 시점에 80 포트를 certbot이 직접 사용해야 하므로,
nginx 컨테이너가 실행 중이면 잠시 중지해야 한다.

```bash
# certbot 설치
sudo apt-get install -y certbot

# nginx가 실행 중이면 먼저 중지
cd ~/actions-runner/_work/gifttax/gifttax
docker compose --env-file /etc/gifttax/gifttax.env down

# 인증서 발급 (standalone 방식)
sudo certbot certonly --standalone -d <your-domain>

# 인증서 발급 후 서비스 재시작
docker compose --env-file /etc/gifttax/gifttax.env up -d

# 발급된 인증서 위치
# /etc/letsencrypt/live/<your-domain>/fullchain.pem
# /etc/letsencrypt/live/<your-domain>/privkey.pem
```

### 서버 환경변수 파일 생성

공개 저장소에는 실제 운영 도메인을 넣지 않고, 서버에만 환경변수 파일을 둔다.

```bash
sudo mkdir -p /etc/gifttax
sudo tee /etc/gifttax/gifttax.env > /dev/null <<'EOF'
CERT_DOMAIN=<your-domain>
LETSENCRYPT_DIR=/etc/letsencrypt
EOF
```

이 파일은 `deploy.yml`에서 `docker compose --env-file /etc/gifttax/gifttax.env ...` 형식으로 사용한다.

저장소에는 예시 파일 `.env.deploy.example`만 포함되어 있다.
실제 배포에서는 예시 파일을 수정하지 말고, 서버의 `/etc/gifttax/gifttax.env`만 관리한다.

### docker-compose.yml의 letsencrypt 연결

`docker-compose.yml`은 기본값으로 호스트의 `/etc/letsencrypt`를 bind mount 한다.

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

### 자동 갱신 설정

```bash
# crontab에 자동 갱신 추가
sudo crontab -e

# 매월 1일 새벽 3시에 갱신 시도
# standalone 방식이므로 갱신 전 nginx를 중지하고, 갱신 후 다시 시작
0 3 1 * * cd ~/actions-runner/_work/gifttax/gifttax && docker compose --env-file /etc/gifttax/gifttax.env stop nginx && certbot renew --quiet && docker compose --env-file /etc/gifttax/gifttax.env up -d nginx
```

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
