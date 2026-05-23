import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { defineConfig } from "vite";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const live2dRoot = path.resolve(__dirname, "../assets/live2d");

function contentType(filePath) {
  const ext = path.extname(filePath).toLowerCase();
  if (ext === ".json") return "application/json; charset=utf-8";
  if (ext === ".png") return "image/png";
  if (ext === ".moc3") return "application/octet-stream";
  if (ext === ".mtn" || ext === ".motion3") return "application/json; charset=utf-8";
  return "application/octet-stream";
}

function live2dAssetPlugin() {
  return {
    name: "serve-live2d-assets",
    configureServer(server) {
      server.middlewares.use("/live2d", (req, res, next) => {
        const rawUrl = decodeURIComponent((req.url || "").split("?")[0] || "/");
        const relativeUrl = rawUrl.replace(/^\/+/, "");
        const filePath = path.resolve(live2dRoot, relativeUrl);

        if (!filePath.startsWith(live2dRoot)) {
          res.statusCode = 403;
          res.end("Forbidden");
          return;
        }
        if (!fs.existsSync(filePath) || !fs.statSync(filePath).isFile()) {
          next();
          return;
        }

        res.setHeader("Content-Type", contentType(filePath));
        fs.createReadStream(filePath).pipe(res);
      });
    },
  };
}



export default defineConfig({
  plugins: [live2dAssetPlugin()],
  server: {
    host: "127.0.0.1",
    port: 5174,
  },
});
