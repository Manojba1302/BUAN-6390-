-- Align the default W-2 purchase checklist with the supplied workflow.
UPDATE checklist_requirement SET required_count = 2, guidance = 'W-2s for the two most recent tax years' WHERE document_tag = 'w2';
