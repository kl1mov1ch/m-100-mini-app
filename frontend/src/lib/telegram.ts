import { telegramLightBackground } from './telegram-theme';

export async function initializeTelegram(): Promise<void> {
	if (!location.hash.includes('tgWebAppData=') || window.Telegram?.WebApp) return;
	await new Promise<void>((resolve, reject) => {
		const script = document.createElement('script');
		script.src = 'https://telegram.org/js/telegram-web-app.js';
		const timeout = setTimeout(() => reject(new Error('Не удалось загрузить Telegram SDK')), 12000);
		script.onload = () => {
			clearTimeout(timeout);
			resolve();
		};
		script.onerror = () => {
			clearTimeout(timeout);
			reject(new Error('Не удалось загрузить Telegram SDK'));
		};
		document.head.appendChild(script);
	});
}

export function configureTelegram(): void {
	const app = window.Telegram?.WebApp;
	if (!app?.initData) return;
	document.documentElement.dataset.telegram = 'true';
	const updateViewport = () => {
		const style = document.documentElement.style;
		style.setProperty('--app-height', `${app.viewportHeight || window.innerHeight}px`);
		for (const side of ['top', 'bottom', 'left', 'right'] as const) {
			const safe = app.safeAreaInset?.[side] || 0;
			const content = app.contentSafeAreaInset?.[side] || 0;
			style.setProperty(`--app-safe-${side}`, `${safe + content}px`);
		}
	};
	updateViewport();
	app.onEvent('viewportChanged', updateViewport);
	if (app.isVersionAtLeast('8.0')) {
		app.onEvent('safeAreaChanged', updateViewport);
		app.onEvent('contentSafeAreaChanged', updateViewport);
	}
	if (app.isVersionAtLeast('6.1')) {
		app.setHeaderColor('#ffffff');
		app.setBackgroundColor(telegramLightBackground);
	}
	if (app.isVersionAtLeast('7.10')) app.setBottomBarColor?.('#ffffff');
	app.expand();
}

export function openExternalLink(event: { preventDefault(): void }, url?: string): void {
	const app = window.Telegram?.WebApp;
	if (url && app?.initData && app.isVersionAtLeast('6.1')) {
		event.preventDefault();
		app.openLink(url);
	}
}
