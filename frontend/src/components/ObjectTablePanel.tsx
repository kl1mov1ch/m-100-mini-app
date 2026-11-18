import { Alert, App, Upload } from 'antd';
import { Select } from './Select';
import { Input } from './Input';
import { Button } from './Button';
import { Download, FileSearch, Settings2, Trash2, Unlink } from 'lucide-react';
import { ChevronDown } from './kit-icons';
import { useId, useState } from 'react';
import type { WorkspaceView } from '../App';
import { FieldHelp } from './FieldHelp';
import { ObjectTableCard } from './ObjectTableCard';
import { ObjectDiskFiles } from './ObjectDiskFiles';
import { request } from '../lib/api';
import { openExternalLink } from '../lib/telegram';
import { downloadReport } from '../lib/report-download';
import './object-table-panel.css';

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
	const webhookFieldId = useId();
	const [manualLink, setManualLink] = useState('');
	const [checkingLink, setCheckingLink] = useState(false);
	const saveShareLink = async () => {
		setCheckingLink(true);
		try {
			await request('/bitrix/disk-book/share-link', { url: manualLink }, workspace.project);
			await workspace.loadData(workspace.project, true);
			setManualLink('');
		} catch (failure) {
			message.error((failure as Error).message);
		} finally {
			setCheckingLink(false);
		}
	};
	const { message } = App.useApp();
	const {
		data,
		positions,
		url,
		setUrl,
		webhookId,
		setWebhookId,
		diskWebhooks,
		saveDiskWebhook,
		busy,
		upload,
		importRemote,
		resumeImport,
		retryJournal,
		reviewOriginalTable,
	} = workspace;
	const config = data?.config;
	if (!config) return null;
	const connected = config.source === 'bitrix';
	const detached = config.source === 'detached';
	const ready = positions.length > 0 && !config.pending_import;
	const currentWebhookId = webhookId || config.webhook_profile_id || undefined;
	const saveCurrentWebhook = async () => {
		try {
			const saved = await saveDiskWebhook({ project_id: workspace.project });
			setWebhookId(saved.id);
			message.success('Вебхук сохранён в профиле');
		} catch (error) {
			message.error((error as Error).message);
		}
	};
	return (
		<section className="object-panel table-panel">
			<div className="object-panel-heading">
				<h2>Таблица проекта</h2>
				<Button
					type="text"
					size="small"
					aria-pressed={workspace.evenSpacing}
					onClick={() => workspace.setEvenSpacing(!workspace.evenSpacing)}
				>
					{workspace.evenSpacing ? 'Обычные отступы' : 'Выровнять отступы'}
				</Button>
			</div>
			{connected ? (
				<>
					<ObjectTableCard workspace={workspace} />
					{config.has_webhook && config.file_id > 0 && config.journal_status !== 'ready' && (
						<Alert
							type="warning"
							showIcon
							message={config.journal_note || 'Проверьте запись листа «Журнал работ» в Битрикс24'}
							description={
								<Button size="small" loading={busy} onClick={retryJournal}>
									Повторить запись
								</Button>
							}
						/>
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
			<div className="table-setup-actions">
				<button
					type="button"
					className="table-settings-toggle"
					aria-expanded={configuring}
					onClick={() => setConfiguring(!configuring)}
				>
					<Settings2 size={17} aria-hidden />
					<span>{connected ? 'Настройки подключения' : 'Подключить Битрикс24'}</span>
					<ChevronDown size={17} className={configuring ? 'is-open' : ''} aria-hidden />
				</button>
				{!connected && (
					<Upload accept=".xlsx,.csv" maxCount={1} showUploadList={false} beforeUpload={upload}>
						<Button loading={busy}>Загрузить Excel</Button>
					</Upload>
				)}
				{config.source === 'file' && ready && (
					<Button
						icon={<Download size={16} />}
						onClick={() =>
							void downloadReport('/imports/workbook.xlsx', workspace.project).catch(
								(error: Error) => message.error(error.message),
							)
						}
					>
						Скачать журнал
					</Button>
				)}
			</div>
			<ObjectDiskFiles workspace={workspace} />
			{connected && config.bitrix_project_book?.id === config.file_id && (
				<section className="disk-files">
					<h3>Доступ для просмотра</h3>
					{config.bitrix_project_book.share_url ? (
						<Button
							type="text"
							href={config.bitrix_project_book.share_url}
							onClick={(e) => openExternalLink(e, config.bitrix_project_book!.share_url!)}
						>
							Открыть публичную ссылку
						</Button>
					) : (
						<>
							<p>
								В Битрикс24 откройте файл Excel, выберите «Поделиться» и включите просмотр по
								ссылке. Вставьте публичную ссылку на таблицу. Если доступ ограничен, обратитесь к
								администратору портала.
							</p>
							<label>
								Публичная ссылка на Excel
								<Input
									value={manualLink}
									onChange={(e) => setManualLink(e.target.value)}
									placeholder="https://bitrix24public.com/…"
								/>
							</label>
							<Button
								type="text"
								disabled={!manualLink.trim()}
								loading={checkingLink}
								onClick={() => void saveShareLink()}
							>
								Проверить и сохранить ссылку
							</Button>
						</>
					)}
				</section>
			)}
			{configuring && (
				<div className="object-connection-form table-settings-form">
					<label>
						Ссылка на таблицу Битрикс24
						<Input
							value={url}
							onChange={(event) => setUrl(event.target.value)}
							placeholder="https://bitrix24public.com/…"
						/>
					</label>
					<div>
						<div className="help-field-heading">
							<label htmlFor={webhookFieldId}>Вебхук для записи</label>
							<FieldHelp topic="bitrix" />
						</div>
						<Select
							id={webhookFieldId}
							aria-label="Вебхук для записи"
							value={
								diskWebhooks.some(({ id }) => id === currentWebhookId)
									? currentWebhookId
									: undefined
							}
							onChange={setWebhookId}
							placeholder={config.has_webhook ? 'Текущий вебхук объекта' : 'Выберите из профиля'}
							options={diskWebhooks.map(({ id, name, portal }) => ({
								value: id,
								label: name === portal ? portal : name + ' · ' + portal,
							}))}
						/>
					</div>
					<div className="object-panel-actions">
						{config.has_webhook && !currentWebhookId && (
							<Button onClick={() => void saveCurrentWebhook()}>Сохранить текущий в профиль</Button>
						)}
						<Button type="text" onClick={() => workspace.setPage('more')}>
							Вебхуки в профиле
						</Button>
					</div>
					<Button
						type="primary"
						loading={busy}
						disabled={!url.trim() && !(config.file_id && (currentWebhookId || config.has_webhook))}
						onClick={importRemote}
					>
						{connected ? 'Применить подключение' : 'Подключить таблицу'}
					</Button>
					{connected && (
						<Button
							type="text"
							icon={<FileSearch size={16} />}
							loading={busy}
							disabled={workspace.checkingConnection}
							onClick={reviewOriginalTable}
						>
							Проверить исходные листы
						</Button>
					)}
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

			<div className="object-danger-zone">
				{(connected || config.public_url || config.has_webhook) && (
					<Button
						type="text"
						danger
						icon={<Unlink size={17} />}
						disabled={loadingAction || busy || workspace.checkingConnection}
						onClick={onDetach}
					>
						Отвязать таблицу
					</Button>
				)}
				<Button
					type="text"
					danger
					icon={<Trash2 size={17} />}
					loading={loadingAction}
					disabled={busy || workspace.checkingConnection}
					onClick={onDelete}
				>
					Удалить объект
				</Button>
			</div>
		</section>
	);
}
