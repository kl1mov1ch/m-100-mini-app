import { Button, Spin } from 'antd';
import { ArrowUpRight, RotateCw } from 'lucide-react';
import { RequestError } from '../lib/api';
import './launch-screen.css';

const botLink = 'https://t.me/m1OOtest_bot';

export function LaunchScreen({ failure }: { failure: Error | null }) {
	if (!failure) {
		return (
			<main className="launch-screen" aria-busy="true">
				<div className="launch-loading" role="status">
					<Spin size="small" />
					<span>Открываем объекты…</span>
				</div>
			</main>
		);
	}

	const needsTelegram = failure instanceof RequestError && failure.status === 401;
	const openedInTelegram = Boolean(
		window.Telegram?.WebApp || location.hash.includes('tgWebAppData='),
	);
	const heading = needsTelegram
		? openedInTelegram
			? 'Откройте приложение заново'
			: 'Откройте в Telegram'
		: 'Не удалось открыть журнал';
	const description = needsTelegram
		? openedInTelegram
			? 'Закройте это окно и запустите журнал из меню бота M-100.'
			: 'Перейдите к боту M-100 и откройте журнал из его меню.'
		: failure instanceof RequestError
			? failure.message
			: 'Проверьте подключение к интернету и повторите попытку.';

	return (
		<main className="launch-screen">
			<section className="launch-card" aria-labelledby="launch-heading">
				<img
					className="launch-logo"
					src="/brand/m100-animated.svg?v=4"
					width={76}
					height={23}
					alt="М100"
				/>
				<div className="launch-copy">
					<h1 id="launch-heading">{heading}</h1>
					<p role="alert">{description}</p>
				</div>
				{needsTelegram ? (
					<Button
						type="primary"
						href={botLink}
						icon={<ArrowUpRight size={16} />}
						onClick={(event) => {
							const app = window.Telegram?.WebApp;
							if (!app?.openTelegramLink) return;
							event.preventDefault();
							app.openTelegramLink(botLink);
						}}
					>
						Открыть бота
					</Button>
				) : (
					<Button type="primary" icon={<RotateCw size={16} />} onClick={() => location.reload()}>
						Повторить
					</Button>
				)}
			</section>
		</main>
	);
}
