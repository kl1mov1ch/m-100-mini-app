import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';
export default defineConfig(({ command }) => {
	const release = command === 'build' ? crypto.randomUUID() : 'development';
	return {
		plugins: [
			react(),
			{
				name: 'app-release',
				apply: 'build',
				generateBundle() {
					this.emitFile({
						type: 'asset',
						fileName: 'app-release.json',
						source: JSON.stringify({ release }),
					});
				},
			},
		],
		define: { __APP_RELEASE__: JSON.stringify(release) },
		server: {
			port: 5173,
			strictPort: true,
			watch: { awaitWriteFinish: { stabilityThreshold: 350, pollInterval: 80 } },
			proxy: { '/api': 'http://127.0.0.1:8000' },
		},
		preview: { port: 5173 },
	};
});
