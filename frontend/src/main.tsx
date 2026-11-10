import '@ant-design/v5-patch-for-react-19';
import { renderApp } from './App';
import { configureTelegram, initializeTelegram } from './lib/telegram';
initializeTelegram()
	.catch(() => undefined)
	.then(() => {
		configureTelegram();
		renderApp();
	});
