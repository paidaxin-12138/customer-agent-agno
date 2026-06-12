// Copyright (c) 2026 paidaxin-12138
// Licensed under CC BY-NC 4.0 — see LICENSE in repository root.
// https://creativecommons.org/licenses/by-nc/4.0/
/**
 * PM2 进程守护 — Customer-Agent 桌面客服
 *
 * 安装: npm i -g pm2
 * 启动: pm2 start ecosystem.config.js
 * 开机自启: pm2 save && pm2 startup
 *
 * 说明：PyQt6 需要图形会话；Linux 无头请配合 xvfb 或本机桌面登录。
 */
module.exports = {
  apps: [
    {
      name: "customer-agent",
      cwd: __dirname,
      script: ".venv/bin/python",
      args: "app.py",
      interpreter: "none",
      instances: 1,
      autorestart: true,
      max_restarts: 50,
      min_uptime: "10s",
      restart_delay: 5000,
      max_memory_restart: "2G",
      // 就绪探针（需在 .env 配置 HEALTH_CHECK_TOKEN）:
      // curl -sf -H "Authorization: Bearer $HEALTH_CHECK_TOKEN" http://127.0.0.1:8080/ready || pm2 restart customer-agent
      watch: false,
      merge_logs: true,
      out_file: "logs/out.log",
      error_file: "logs/error.log",
      log_date_format: "YYYY-MM-DD HH:mm:ss Z",
      // 日志按日轮转由 Python utils/logging_setup.py 负责（out.log / error.log 保留 7 天）。
      // 若需 PM2 自身进程日志轮转，请额外安装: pm2 install pm2-logrotate
      env: {
        PYTHONUNBUFFERED: "1",
        LOG_LEVEL: "info",
        LLM_MODEL_NAME: "qwen-turbo",
        LLM_MAX_TOKENS: "500",
        LLM_TEMPERATURE: "0.5",
        MESSAGE_CONSUMER_MAX_CONCURRENT: "16",
      },
      env_production: {
        ENVIRONMENT: "production",
      },
    },
  ],
};
