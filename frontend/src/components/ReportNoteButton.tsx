import { Button } from 'antd';
import { SheetModal as Modal } from './SheetModal';
import { MessageSquareText } from 'lucide-react';
import { useState } from 'react';
import { NoteInput } from './NoteInput';
import { readFormDraft, removeFormDraft, writeFormDraft } from '../lib/form-drafts';

export function ReportNoteButton({
	userId,
	project,
	scope,
	label,
	value,
	onChange,
	maxLength,
}: {
	userId: string;
	project: string;
	scope: string;
	label: string;
	value: string;
	onChange: (value: string) => void;
	maxLength?: number;
}) {
	const [open, setOpen] = useState(false);
	const [draft, setDraft] = useState('');
	const draftKey = `note:${userId}:${project}:${scope}`;
	return (
		<>
			<Button
				className="report-note-button"
				aria-label={label + (value.trim() ? ', заполнено' : '')}
				aria-haspopup="dialog"
				data-filled={!!value.trim()}
				icon={<MessageSquareText size={16} aria-hidden />}
				onClick={() => {
					const saved = readFormDraft<{ base: string; text: string }>(draftKey);
					setDraft(saved?.base === value ? saved.text : value);
					setOpen(true);
				}}
			>
				Примечание
			</Button>
			<Modal
				className="report-note-editor"
				title={label}
				open={open}
				destroyOnHidden
				okText="Применить"
				footer={(_, { OkBtn }) => <OkBtn />}
				onCancel={() => setOpen(false)}
				onOk={() => {
					onChange(draft);
					removeFormDraft(draftKey);
					setOpen(false);
				}}
			>
				<NoteInput
					project={project}
					scope={scope}
					value={draft}
					onChange={(text) => {
						setDraft(text);
						if (text === value) removeFormDraft(draftKey);
						else writeFormDraft(draftKey, { base: value, text });
					}}
					label={label}
					maxLength={maxLength}
				/>
			</Modal>
		</>
	);
}
