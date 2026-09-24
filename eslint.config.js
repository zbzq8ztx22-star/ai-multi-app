import globals from "globals";
import react from "eslint-plugin-react";

export default [
  {
    files: ["src/**/*.{js,jsx}"],
    plugins: { react },
    languageOptions: {
      ecmaVersion: 2022,
      sourceType: "module",
      parserOptions: { ecmaFeatures: { jsx: true } },
      globals: { ...globals.browser },
    },
    settings: { react: { version: "18.3" } },
    rules: {
      "no-undef": "error",
      "no-unused-vars": ["error", { argsIgnorePattern: "^_", varsIgnorePattern: "^[A-Z_]" }],
      "no-constant-condition": "error",
      "no-dupe-keys": "error",
      "no-duplicate-case": "error",
      "no-empty": ["error", { allowEmptyCatch: true }],
      "no-unreachable": "error",
      "react/jsx-uses-vars": "error",
      "react/jsx-uses-react": "off",
      "react/react-in-jsx-scope": "off",
    },
  },
];
