"""Production runs behind nginx on loopback; logs are collected by journald."""
bind = '127.0.0.1:8087'
workers = 3
worker_class = 'gthread'
threads = 2
timeout = 30
graceful_timeout = 30
accesslog = '-'
errorlog = '-'
capture_output = True
# Invite/update tokens are URLs. Do not write request paths to access logs.
access_log_format = '%(h)s %(t)s %(m)s %(s)s %(L)s'
forwarded_allow_ips = '127.0.0.1'
