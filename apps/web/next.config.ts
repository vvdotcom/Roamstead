import type { NextConfig } from "next";
import { existsSync, readFileSync } from "node:fs";
import { resolve } from "node:path";

function rootEnvironmentValue(name: string) {
  const path = resolve(process.cwd(), "../..", ".env");
  if (!existsSync(path)) return undefined;
  const line = readFileSync(path, "utf8")
    .split(/\r?\n/)
    .find((value) => value.trimStart().startsWith(`${name}=`));
  if (!line) return undefined;
  const value = line.slice(line.indexOf("=") + 1).trim();
  return value.replace(/^(['"])(.*)\1$/, "$2");
}

const mapsBrowserKey = process.env.NEXT_PUBLIC_GOOGLE_MAPS_API_KEY
  ?? process.env.GOOGLE_MAPS_API_KEY
  ?? rootEnvironmentValue("GOOGLE_MAPS_API_KEY")
  ?? "";

const nextConfig: NextConfig = {
  output: "standalone",
  allowedDevOrigins: ["127.0.0.1", "localhost"],
  env: {
    NEXT_PUBLIC_GOOGLE_MAPS_API_KEY: mapsBrowserKey,
  },
  async rewrites() {
    return [
      {
        source: "/api/:path*",
        destination: `${process.env.API_URL ?? "http://127.0.0.1:8000"}/api/:path*`,
      },
    ];
  },
};

export default nextConfig;
