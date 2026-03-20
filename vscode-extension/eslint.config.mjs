// @ts-check

import eslint from "@eslint/js";
import tseslint from "typescript-eslint";

export default tseslint.config(
    { ignores: ["**/*.js", "node_modules/**", "out/**"] },
    {
        files: ["src/**/*.ts"],
        extends: [eslint.configs.recommended, tseslint.configs.recommended],
        rules: {
            "@typescript-eslint/no-explicit-any": "off",
            "@typescript-eslint/no-unused-vars": "off",
            "no-prototype-builtins": "off",
            "@typescript-eslint/no-require-imports": "off"
        }
    }
);
