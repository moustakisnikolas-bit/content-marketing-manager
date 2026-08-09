import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  // Lets the Docker image ship only the traced server bundle + deps,
  // instead of the full node_modules tree.
  output: "standalone",
};

export default nextConfig;
