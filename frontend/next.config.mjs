import { fileURLToPath } from "node:url";

const configuredBackend = process.env.API_BACKEND_URL;

if (!configuredBackend && process.env.NODE_ENV === "production") {
  throw new Error(
    "Configure API_BACKEND_URL com a URL HTTPS do serviço Render.",
  );
}

const backend = new URL(configuredBackend || "http://127.0.0.1:8000");
if (!["http:", "https:"].includes(backend.protocol)) {
  throw new Error("API_BACKEND_URL deve começar com http:// ou https://.");
}

const backendOrigin = backend.origin;

const nextConfig = {
  agentRules: false,
  turbopack: {
    root: fileURLToPath(new URL(".", import.meta.url)),
  },
  async rewrites() {
    return [
      {
        source: "/api/:path*",
        destination: `${backendOrigin}/api/:path*`,
      },
    ];
  },
};

export default nextConfig;
