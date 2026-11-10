import { useEffect } from 'react';

export function useTelegramNavigation(back: (() => void) | undefined, unsaved: boolean): void {
	useEffect(() => {
		const app = window.Telegram?.WebApp;
		if (!app?.initData || !app.isVersionAtLeast('6.1')) return;
		if (!back) {
			app.BackButton.hide();
			return;
		}
		app.BackButton.show();
		app.BackButton.onClick(back);
		return () => app.BackButton.offClick(back);
	}, [back]);
	useEffect(() => {
		const app = window.Telegram?.WebApp;
		if (!app?.initData || !app.isVersionAtLeast('6.2')) return;
		if (unsaved) app.enableClosingConfirmation();
		else app.disableClosingConfirmation();
		return () => app.disableClosingConfirmation();
	}, [unsaved]);
}
