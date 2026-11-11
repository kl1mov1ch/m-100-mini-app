import { Alert, Button, Input, Upload } from 'antd';
import { Trash2, Unlink } from 'lucide-react';
import { useState } from 'react';
import type { WorkspaceView } from '../App';
import { FieldHelp } from './FieldHelp';
import { BitrixReadStatus } from './BitrixReadStatus';
import { ObjectTableCard } from './ObjectTableCard';

export function ObjectTablePanel({
	workspace,
	onDetach,
	onDelete,
	loadingAction,
}: {
	workspace: WorkspaceView;
	onDetach: () => void;
	onDelete: () => void;
	loadingAction: boolean;
}) {
	const [configuring, setConfiguring] = useState(false);
	const {
		data,
		positions,
		url,
		setUrl,
		webhook,
		setWebhook,
		busy,
		upload,
		importRemote,
		resumeImport,
		openObjectSection,
	} = workspace;
	const config = data?.config;
	if (!config) return null;
	const connected = config.source === 'bitrix';
	const detached = config.source === 'detached';
	const ready = positions.length > 0 && !config.pending_import;
	return (
		<section className="object-panel">
			<div className="object-panel-heading">
				<h2>Таблица</h2>
				{(connected || config.public_url || config.has_webhook) && (
					<Button danger icon={<Unlink size={16} />} onClick={onDetach}>
						Отвязать
					</Button>
				)}
			</div>
			{connected ? (
				<>
					<ObjectTableCard workspace={workspace} />
					<BitrixReadStatus workspace={workspace} />
					{config.journal_status === 'pending' && config.journal_note && (
						<Alert type="warning" showIcon message={config.journal_note} />
					)}
				</>
			) : (
				<>
					{detached && (
						<Alert
							type="warning"
							showIcon
							message="Таблица отвязана. Отчёты сохраняются в приложении."
						/>
					)}
					{ready ? (
						<p>
							<b>{config.source_name}</b> · {positions.length} работ
						</p>
					) : (
						<p>
							Подключите Битрикс24 или загрузите файл Excel. После чтения проверьте позиции сметы.
						</p>
					)}
				</>
			)}
			<div className="object-panel-actions">
				<Button
					type={!connected && !configuring ? 'primary' : 'default'}
					onClick={() => setConfiguring(!configuring)}
				>
					{configuring
						? 'Скрыть настройки'
						: connected
							? 'Настроить подключение'
							: 'Подключить Битрикс24'}
				</Button>
				{!connected && (
					<Upload accept=".xlsx,.csv" maxCount={1} showUploadList={false} beforeUpload={upload}>
						<Button loading={busy}>Загрузить Excel</Button>
					</Upload>
				)}
			</div>
			{configuring && (
				<div className="object-connection-form">
					<label>
						Ссылка на таблицу Битрикс24
						<Input
							value={url}
							onChange={(event) => setUrl(event.target.value)}
							placeholder="https://bitrix24public.com/…"
						/>
					</label>
					<details>
						<summary>Доступ для автоматической отправки</summary>
						<label>
							Вебхук с правом «Диск» <FieldHelp topic="bitrix" />
							<Input.Password
								value={webhook}
								onChange={(event) => setWebhook(event.target.value)}
								placeholder={
									config.has_webhook ? 'Вебхук сохранён' : 'https://ваш-портал.bitrix24.by/rest/…'
								}
								autoComplete="off"
							/>
						</label>
					</details>
					<Button
						type="primary"
						loading={busy}
						disabled={!url.trim() && !(config.file_id && (webhook.trim() || config.has_webhook))}
						onClick={importRemote}
					>
						Прочитать таблицу
					</Button>
				</div>
			)}
			{config.pending_import && (
				<Alert
					type="warning"
					showIcon
					message="Проверьте замечания и подтвердите импорт"
					description={
						<Button size="small" loading={busy} onClick={resumeImport}>
							Открыть проверку
						</Button>
					}
				/>
			)}
			{ready && (
				<Button type="primary" onClick={() => openObjectSection('catalogue')}>
					Проверить смету
				</Button>
			)}
			<div className="object-danger-zone">
				<Button
					type="text"
					danger
					icon={<Trash2 size={17} />}
					loading={loadingAction}
					onClick={onDelete}
				>
					Удалить объект
				</Button>
			</div>
		</section>
	);
}
