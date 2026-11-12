import { Button, Modal } from 'antd';
import { CircleHelp, ExternalLink, Info } from 'lucide-react';
import { useState } from 'react';
import { openExternalLink } from '../lib/telegram';
import './field-help.css';

const instructions = {
	bitrix: {
		title: 'Как подключить Битрикс24',
		steps: [
			[
				'Подготовьте таблицу',
				'Загрузите Excel на Диск Битрикс24 и дайте сотруднику доступ на редактирование.',
			],
			[
				'Создайте входящий вебхук',
				'Откройте «Разработчикам» → «Другое» → «Входящий вебхук» и выберите право «Диск».',
			],
			[
				'Сохраните вебхук в профиле',
				'В настройках мастера откройте «Вебхуки Битрикс24» и вставьте адрес вебхука.',
			],
			[
				'Подключите таблицу к объекту',
				'Вставьте ссылку на Excel, выберите сохранённый вебхук и нажмите «Прочитать таблицу».',
			],
			[
				'Подтвердите импорт',
				'Сверьте столбцы и замечания. После подтверждения отчётов приложение сможет обновлять таблицу.',
			],
		],
		note: 'Публичная ссылка позволяет читать файл. Для записи нужен вебхук с правом «Диск».',
		link: 'https://apidocs.bitrix24.com/local-integrations/local-webhooks.html',
		linkLabel: 'Инструкция Битрикс24',
	},
	ai: {
		title: 'Как подключить DeepSeek',
		steps: [
			['Войдите в DeepSeek', 'Откройте платформу DeepSeek и войдите в свой аккаунт.'],
			['Создайте ключ', 'В разделе API keys создайте ключ и скопируйте его.'],
			['Подключите ключ в приложении', 'Вставьте ключ в поле «Ключ API» и нажмите «Подключить».'],
		],
		note: 'Приложение сначала ищет позиции в смете. DeepSeek подключается, когда нужно уточнить совпадение.',
		link: 'https://platform.deepseek.com/api_keys',
		linkLabel: 'Открыть API keys DeepSeek',
	},
};

export function FieldHelp({ topic }: { topic: keyof typeof instructions }) {
	const [open, setOpen] = useState(false);
	const { title, steps, note, link, linkLabel } = instructions[topic];
	const close = () => setOpen(false);

	return (
		<>
			<button
				className="field-help-button"
				type="button"
				aria-haspopup="dialog"
				aria-expanded={open}
				aria-label={title}
				onClick={() => setOpen(true)}
			>
				<Info size={20} aria-hidden />
			</button>
			<Modal
				rootClassName="field-help-sheet"
				open={open}
				title={title}
				onCancel={close}
				destroyOnHidden
				footer={
					<Button type="primary" onClick={close}>
						Понятно
					</Button>
				}
			>
				<ol className="field-help-steps">
					{steps.map(([heading, text], index) => (
						<li key={heading}>
							<span aria-hidden="true">{index + 1}</span>
							<div>
								<strong>{heading}</strong>
								<p>{text}</p>
							</div>
						</li>
					))}
				</ol>
				<div className="field-help-note">
					<CircleHelp size={18} aria-hidden />
					<p>{note}</p>
				</div>
				<a
					className="field-help-link"
					href={link}
					target="_blank"
					rel="noreferrer"
					onClick={(event) => openExternalLink(event, link)}
				>
					{linkLabel} <ExternalLink size={15} aria-hidden />
				</a>
			</Modal>
		</>
	);
}
