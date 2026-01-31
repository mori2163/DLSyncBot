module.exports = {
  apps: [
    {
      name: "music-downloader-bot",
      script: "uv",
      args: "run python main.py",
      interpreter: "none", // uv を直接実行するため
      autorestart: true,
      watch: false,
      max_memory_restart: "1G",
      env: {
        NODE_ENV: "production",
      },
      log_date_format: "YYYY-MM-DD HH:mm:ss",
      error_file: "./logs/error.log",
      out_file: "./logs/out.log",
      merge_logs: true,
    },
  ],
};
