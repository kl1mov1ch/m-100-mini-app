import { request } from './api';

export async function downloadReport(path: string, project?: string) {
	const separator = path.includes('?') ? '&' : '?';
	const ticket = await request<{ url: string; filename: string }>(
		`${path}${separator}prepare=true`,
		undefined,
		project,
	);
	const url = new URL(ticket.url, location.origin).href;
	const telegram = window.Telegram?.WebApp;
	if (telegram?.initData && location.protocol === 'https:') {
		if (telegram.downloadFile && telegram.isVersionAtLeast('8.0')) {
			telegram.downloadFile({ url, file_name: ticket.filename });
		} else {
			telegram.openLink(url);
		}
		return;
	}

	const link = document.createElement('a');
	link.href = url;
	link.download = ticket.filename;
	document.body.append(link);
	link.click();
	link.remove();
}
