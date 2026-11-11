import { useEffect } from 'react';

export function useStartupScreen(ready: boolean) {
	useEffect(() => {
		const screen = document.getElementById('startup-screen');
		if (!ready || !screen) return;

		if (window.matchMedia('(prefers-reduced-motion: reduce)').matches) {
			screen.remove();
			return;
		}

		let removalTimer: number | undefined;
		const revealTimer = window.setTimeout(
			() => {
				screen.classList.add('is-finished');
				screen.setAttribute('aria-hidden', 'true');
				removalTimer = window.setTimeout(() => screen.remove(), 250);
			},
			Math.max(0, 650 - performance.now()),
		);

		return () => {
			window.clearTimeout(revealTimer);
			window.clearTimeout(removalTimer);
		};
	}, [ready]);
}
