import { Popover } from 'antd';

export function FieldHelp({ topic }: { topic: 'bitrix' | 'ai' }) {
	const content =
		topic === 'bitrix' ? (
			<div className="field-help-content">
				<b>Запись в таблицу Битрикс24</b>
				<ol>
					<li>
						Загрузите Excel на Диск Битрикс24 и включите доступ к файлу для нужного сотрудника.
					</li>
					<li>Откройте «Разработчикам» → «Другое» → «Входящий вебхук».</li>
					<li>
						Выберите право «Диск» и создайте вебхук от сотрудника с правом редактировать файл.
					</li>
					<li>
						Скопируйте базовый адрес вебхука в это поле, ссылку на таблицу — выше. Нажмите «Связать
						таблицу с объектом».
					</li>
					<li>Проверьте найденные столбцы, исправьте жёлтые замечания и подтвердите импорт.</li>
				</ol>
				<p>
					После подтверждения отчёта приложение обновляет объёмы и расчёты. Публичной ссылки для
					записи недостаточно. Вебхук хранится на сервере и может использоваться вашим AI-агентом
					только через серверную интеграцию.
				</p>
				<a
					href="https://apidocs.bitrix24.com/local-integrations/local-webhooks.html"
					target="_blank"
					rel="noreferrer"
				>
					Официальная инструкция Битрикс24
				</a>
			</div>
		) : (
			<div className="field-help-content">
				<b>Ключ для умного подбора</b>
				<ol>
					<li>Откройте платформу DeepSeek и войдите в свой аккаунт.</li>
					<li>В разделе API keys создайте ключ и скопируйте его.</li>
					<li>Вставьте ключ в это поле и нажмите «Подключить».</li>
				</ol>
				<p>
					Уже выбрана экономная модель DeepSeek Flash. Сначала ищет код; AI подключается при
					неоднозначном тексте. Ключ провайдера и вебхук Битрикс — разные настройки.
				</p>
				<a href="https://platform.deepseek.com/api_keys" target="_blank" rel="noreferrer">
					Открыть API keys DeepSeek
				</a>
			</div>
		);
	return (
		<Popover
			trigger="click"
			content={content}
			placement="bottom"
			overlayClassName="field-help-popover"
		>
			<button
				className="field-help-button"
				type="button"
				aria-label={topic === 'bitrix' ? 'Как подключить Битрикс24' : 'Как получить AI API ключ'}
			>
				i
			</button>
		</Popover>
	);
}
