FROM mcr.microsoft.com/playwright:v1.61.1-noble
ENV NODE_ENV=production \
    HOME=/tmp/browser-home \
    PORT=8079
WORKDIR /app
COPY package.json package-lock.json ./
RUN npm ci --omit=dev --ignore-scripts && npm cache clean --force
COPY browser.mjs server.mjs ./
USER pwuser
EXPOSE 8079
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
  CMD node -e "fetch('http://127.0.0.1:8079/health').then(r=>process.exit(r.ok?0:1)).catch(()=>process.exit(1))"
CMD ["node", "server.mjs"]
