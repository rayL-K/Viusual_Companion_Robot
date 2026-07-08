import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { defineConfig } from "vite";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const live2dRoot = path.resolve(__dirname, "../assets/live2d");
const live2dModelName = "Strawberry_Rabbit";

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
        let rawUrl;
        try {
          rawUrl = decodeURIComponent((req.url || "").split("?")[0] || "/");
        } catch {
          res.statusCode = 400;
          res.end("Bad Request");
          return;
        }
        if (rawUrl.includes("\0")) {
          res.statusCode = 400;
          res.end("Bad Request");
          return;
        }
        const relativeUrl = rawUrl.replace(/^\/+/, "");
        const filePath = path.resolve(live2dRoot, relativeUrl);
        const relativePath = path.relative(live2dRoot, filePath);

        if (relativePath.startsWith(`..${path.sep}`) || relativePath === ".." || path.isAbsolute(relativePath)) {
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
    closeBundle() {
      const source = path.join(live2dRoot, live2dModelName);
      const target = path.resolve(__dirname, "dist/live2d", live2dModelName);
      fs.cpSync(source, target, { recursive: true });
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
