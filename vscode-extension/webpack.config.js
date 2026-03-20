"use strict";

const path = require("path");

/** @type {import("webpack").Configuration} */
module.exports = {
  target: "node",
  mode: process.env.NODE_ENV === "production" ? "production" : "development",
  entry: "./src/extension.ts",
  output: {
    path: path.resolve(__dirname, "out"),
    filename: "extension.js",
    libraryTarget: "commonjs2",
    devtoolModuleFilenameTemplate: "../[resource-path]",
  },
  externals: {
    vscode: "commonjs vscode",
  },
  resolve: {
    extensions: [".ts", ".js"],
  },
  module: {
    rules: [
      {
        test: /\.ts$/,
        exclude: /node_modules/,
        use: {
          loader: "ts-loader",
          options: {
            transpileOnly: true,
          },
        },
      },
    ],
  },
  devtool: "source-map",
  ignoreWarnings: [
    // vscode-languageserver-protocol dynamic require
    /Critical dependency: require function is used in a way in which dependencies cannot be statically extracted/,
  ],
  infrastructureLogging: {
    level: "error",
  },
};
