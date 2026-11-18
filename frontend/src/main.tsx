import '@telegram-apps/telegram-ui/dist/styles.css';
import { renderApp } from './App';
import { configureTelegram, initializeTelegram } from './lib/telegram';
initializeTelegram()
	.catch(() => undefined)
	.then(() => {
		configureTelegram();
		renderApp();
	});
