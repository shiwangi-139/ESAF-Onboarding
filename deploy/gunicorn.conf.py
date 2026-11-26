# gunicorn settings for the server. Started by deploy/csp-onboarding.service.
bind = "127.0.0.1:8000"          # only nginx can reach the app
chdir = "/srv/csp-onboarding/app/webform"
wsgi_app = "app:app"
workers = 3
threads = 2
timeout = 120                    # document generation (LibreOffice) can take a few seconds
max_requests = 1000              # recycle workers to keep memory steady
max_requests_jitter = 100
accesslog = "-"                  # goes to journald
errorlog = "-"
forwarded_allow_ips = "127.0.0.1"
limit_request_line = 8190
