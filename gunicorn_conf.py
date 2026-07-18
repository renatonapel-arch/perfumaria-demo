import os
bind = f"0.0.0.0:{os.environ.get('PORT','5006')}"
workers = 2
threads = 4
timeout = 60
accesslog = "-"
errorlog = "-"
loglevel = "info"
