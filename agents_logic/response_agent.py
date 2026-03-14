"""
================================================================================
Response Generator Agent — "Report Compiler" (Structured Fact Passing)
================================================================================
RESPONSIBILITY: Format and synthesize structured facts + discrepancy verdict
                from domain agents into a final report. Absolutely NO domain
                logic or specific entity hardcoding allowed here.
================================================================================
"""

import json
import re
from shared.graph_state import GraphState
from shared.agent_base import vera_agent
from shared.schemas import ExtractedFact, DiscrepancyVerdict, ConflictStatus
import shared.config as config
from shared.advanced_rag import NO_DATA_MARKER
from shared.config import llm_invoke_with_retry
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.output_parsers import StrOutputParser

# ---------------------------------------------------------------------------
# Structured "Data Not Found" report template
# ---------------------------------------------------------------------------
_DATA_NOT_FOUND_MSG = (
    "⚠️ **Data Not Found:** I can only answer based on the provided source documents "
    "and database records. No relevant information was found for your query in the "
    "current domain."
)

# ---------------------------------------------------------------------------
# Meta / capability query detection & canned response
# ---------------------------------------------------------------------------
_META_PATTERNS = [
    "what can you do", "what can u do", "what do you do",
    "who are you", "what are you", "what is vera",
    "help me", "how do you work", "what are your capabilities",
    "what can vera do", "introduce yourself", "tell me about yourself",
]

def _get_vera_capabilities() -> str:
    return (
        "🤖 **VERA — Verified Evidence & Retrieval Assistant**\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
        "I am an AI auditing assistant that cross-references multiple data sources to give you **verified answers**.\n\n"
        "📊 **Database Queries**: Look up production records, specs, and histories.\n"
        "📄 **Document Retrieval**: Search SOPs, datasheets, and internal emails.\n"
        "🔍 **Discrepancy Detection**: Flag conflicts between sources automatically.\n"
    )

def _format_facts_as_list(facts: list[dict]) -> str:
    """Simpler format for small models (Llama 3.2 1B) to avoid table parsing errors."""
    if not facts: return "(no facts)"
    lines = []
    for fd in facts:
        try:
            f = ExtractedFact(**fd)
            # Binary Filter
            if "%PDF" in f.value[:10] or "obj <<" in f.value[:50] or f.value.count("\\x") > 5:
                continue
            lines.append(f"- Entity: {f.entity} | Attribute: {f.attribute} | Value: {f.value} (Source: {f.source_type}, Date: {f.date})")
        except: continue
    if not lines: return "(no valid textual facts found)"
    return "\n".join(lines)


@vera_agent("Response Agent")
def run(state: GraphState) -> dict:
    question = state["question"]
    target_entity = state.get("target_entity", "GENERAL")
    target_attribute = state.get("target_attribute", "GENERAL")
    documents = state.get("documents", [])
    official_facts = state.get("official_facts") or []
    informal_facts = state.get("informal_facts") or []
    db_facts = state.get("db_facts") or []
    db_data = state.get("db_data", "") or state.get("db_result", "")
    
    # --- Check if this is a discrepancy report ---
    verdict_dict = state.get("discrepancy_verdict", {}) or {}
    raw_status = verdict_dict.get("overall_status", "")
    status_str = str(raw_status).split(".")[-1].upper()
    is_discrepancy = (status_str == "DISCREPANCY")

    # --- Meta-query shortcut ---
    if any(p in question.lower() for p in _META_PATTERNS):
        return {"generation": _get_vera_capabilities(), "_thinking": "Meta-query response."}

    # --- 核心修订 2: Entity-Strict Context Filtering (Moved Up) ---
    # Filter facts to the target entity for specific (non-generic) queries
    # to prevent the LLM from seeing unrelated background facts.
    is_generic = state.get("is_generic_query", False)
    display_official = official_facts
    display_informal = informal_facts
    display_db = db_facts
    display_db_data = db_data

    # --- 核心修订 2: Strict Domain & Entity Filtering ---
    user_domain = state.get("user_domain", "").lower().strip()
    
    def _domain_matches(f):
        # Facts from DB agent or Doc agents should have 'domain' metadata
        # If missing, assume it belongs to the current domain to avoid information loss
        f_domain = str(f.get('domain', '')).lower().strip()
        return not f_domain or f_domain == user_domain

    display_official = [f for f in official_facts if _domain_matches(f)]
    display_informal = [f for f in informal_facts if _domain_matches(f)]
    display_db = [f for f in db_facts if _domain_matches(f)]
    
    # 🕵️ Debug: Log document domains before filtering
    orig_doc_count = len(documents)
    doc_domains = {str(d.metadata.get("domain", "NONE")).lower() for d in documents}
    
    # Filter documents by domain
    documents = [d for d in documents if str(d.metadata.get("domain", "")).lower().strip() == user_domain]

    # Entity Filter (only for specific queries)
    if not is_generic and target_entity != "GENERAL":
        target_lower = target_entity.lower().strip()
        variations = {target_lower, target_lower.replace("-", " "), target_lower.replace(" ", "-"), target_lower.replace(" ", "")}
        
        def _entity_matches(f):
            e = f.get('entity', '').lower()
            return any(v in e for v in variations if len(v) > 2) or e in ("general", "unknown", "")

        display_official = [f for f in display_official if _entity_matches(f)]
        display_informal = [f for f in display_informal if _entity_matches(f)]
        display_db = [f for f in display_db if _entity_matches(f)]
        
        def _doc_entity_matches(doc):
            c = doc.page_content.lower()
            t = doc.metadata.get("title", "").lower()
            s = doc.metadata.get("source", "").lower()
            entity_match = any(v in c or v in t for v in variations if len(v) > 2)
            is_generic_doc = any(kw in s or kw in t for kw in ("sop", "policy", "handbook", "manual", "regulations"))
            return entity_match or is_generic_doc

        documents = [d for d in documents if _doc_entity_matches(d)]
        
        # If DB data (blob) doesn't mention the entity, clear it from the generator's view
        has_orig_db = bool(db_data and db_data != NO_DATA_MARKER)
        if has_orig_db and not any(v in db_data.lower() for v in variations if len(v) > 2):
            display_db_data = ""

    # --- 核心修复 1: 绝对的物理空值拦截 (Physical Null Check) ---
    # RE-CALCULATE after filtering
    final_has_db = bool(display_db_data and display_db_data != NO_DATA_MARKER)
    has_relevant_context = bool(display_official or display_informal or display_db or final_has_db or documents)
    
    if not has_relevant_context:
        print(f"[Response Agent] 🔒 Information Lock: Context filtered to zero relevance. Forcing 'Data Not Found'.")
        return {"generation": _DATA_NOT_FOUND_MSG, "_thinking": "Context exists but is irrelevant to the target entity."}

    # --- Build Context for LLM ---
    context_parts = [f"Below is the VERIFIED CONTEXT exclusively for the entity '{target_entity}':"]
    if final_has_db: context_parts.append(f"### DATABASE RECORDS FOR '{target_entity}':\n{display_db_data[:1500]}")
    if display_official: context_parts.append(f"### OFFICIAL SPECIFICATIONS FOR '{target_entity}':\n{_format_facts_as_list(display_official)}")
    if display_informal: context_parts.append(f"### INTERNAL COMMUNICATIONS FOR '{target_entity}':\n{_format_facts_as_list(display_informal)}")
    if documents:
        doc_snippet = "\n\n".join([f"[Source {i+1}] {doc.page_content[:800]}" for i, doc in enumerate(documents[:5])])
        context_parts.append(f"### MENTIONED IN PRIMARY DOCUMENTS (RELEVANT TO '{target_entity}'):\n{doc_snippet}")

    debug_info = [
        f"Verified {len(documents)} source documents for domain '{user_domain}'.",
        f"Query context: {'Generic' if is_generic else f'Entity: {target_entity}'}."
    ]

    # --- 核心修复 3: 注入绝对反致幻系统指令 (Anti-Hallucination Prompt) ---
    
    system_instruction = (
        "You are VERA, a verified information assistant. Your goal is to summarize the provided CONTEXT.\n"
        "STRICT RULES:\n"
        "1. SYNTHESIS: List all facts found in the CONTEXT related to the target entity. "
        "If the CONTEXT contains an AUDIT REPORT showing alignment, mention it. "
        "If it shows a conflict, state it clearly.\n"
    )
    
    if is_generic:
        system_instruction += (
            "2. TOPIC-BASED SUMMARY: List ALL distinct details found in the context with their sources.\n"
        )
    else:
        system_instruction += (
            f"2. TARGETED SUMMARY: Focus exclusively on '{target_entity}'. "
            "Ignore any training data you have about this entity; use ONLY the provided context.\n"
        )

    if is_discrepancy:
        system_instruction += (
            "3. DISCREPANCY DETECTED: A conflict exists. Briefly state the conflict at the start. "
            "4. IMPORTANT: Always include specific numbers, dates, and names found in the context.\n"
        )
    else:
        system_instruction += (
            "3. NO DISCREPANCIES: The context shows that all available sources are ALIGNED. "
            "Clearly state that no discrepancies were found. "
            "Summarize the verified information from official and database sources correctly.\n"
        )

    # Include discrepancy report in context if relevant
    report_text = state.get("discrepancy_report", "")
    # AUDIT SHIELD: If authoritative source is NO_DATA, and we are not in generic mode,
    # the discrepancy might be a false positive against irrelevant documents.
    is_false_discrepancy = (NO_DATA_MARKER in report_text and not is_generic)
    
    if report_text and not is_false_discrepancy:
        context_parts.append(f"### AUDIT REPORT:\n{report_text}")

    context_text = "\n\n".join(context_parts)

    prompt = ChatPromptTemplate.from_messages([
        ("system", system_instruction), 
        ("human", "TARGET ENTITY: {entity}\n\nCONTEXT:\n{context}\n\nUSER QUESTION: {question}")
    ])
    
    chain = prompt | config.llm | StrOutputParser()
    raw_response = llm_invoke_with_retry(chain, {
        "entity": target_entity,
        "context": context_text, 
        "question": question
    }).strip()

    # --- Anti-Hallucination Validation (V2: Robust Stop-Words & Refined Regex) ---
    import re
    from shared.dynamic_loader import load_domain_configs
    
    # 1. identify capitalized words (potential entities)
    potential_entities = set(re.findall(r'\b[A-Z][a-zA-Z0-9-]{1,}\b', raw_response))
    
    # 2. Define global "Safe words"
    safe_words = {
        "VERA", "Data", "Not", "Found", "Database", "Official", "Internal", "Sources", 
        "Based", "The", "In", "On", "Of", "At", "By", "For", "With", "From", "And", "Or",
        "Context", "Verified", "Information", "Records", "Review", "Summary", "Entity",
        "According", "As", "To", "This", "That", "It", "Is", "Are", "Was", "Were",
        "Project", "Management", "Required", "Note", "Conflict", "Discrepancy", "Target",
        "Below", "Following", "I", "What", "When", "Who", "Where", "Does", "Do",
        "Specifications", "Technical", "Details", "Status", "Category", "Product", "Material",
        "Authoritative", "Primary", "Documents", "Relevant", "Additional", "Profile", "Records",
        "Description", "Type", "Source", "Date", "Value", "Attributes", "Metrics", "Limits",
        "Warning", "Alert", "Audit", "Report", "Detected", "Conflicts", "Aligned", "Difference",
        "Electrical", "Transmission", "Infection", "Patient", "Clinic", "Hospital",
        "Immediate", "Synthesis", "There", "Since", "Topic", "Topics", "Topics-Based", "Topic-Based",
        "However", "Moreover", "Furthermore", "Additionally", "Consequently", "Therefore",
        "Action", "Actions", "Protocol", "Protocols", "Steps", "Stage", "Level", "Phase",
        "Health", "Medical", "Clinical", "Patient", "Patients", "Isolation", "Audit", "Summary",
        "Reports", "Findings", "Observations", "Recommendations", "Cluster", "Clusters",
        "TB", "Tuberculosis", "Epidemic", "Outbreak", "Prevention", "Control", "Immediate",
        "Action", "Actions", "Protocol", "Protocols", "Policy", "Policies", "Bartowski", "Llama",
        "Assistant", "Verified", "Information", "Context", "Sources", "Source", "According",
        "States", "Mentioned", "Above", "Below", "Provided", "Found", "Details", "Relevant",
        "QUESTION", "Name", "Names", "ALIGNMENT", "USER", "FACTS", "Life", "ANSWER", "Node",
        "Here", "Ship", "Shipping", "Delivery", "Lead", "Time", "Program", "Programme"
    }
    
    # Add target entity and attribute as safe words
    safe_words.add(target_entity)
    safe_words.add(target_attribute)
    # Also add individual words from target entity
    for w in target_entity.split():
        if len(w) > 2: safe_words.add(w)

    # 2b. Domain-Specific safe words
    user_domain = state.get("user_domain", "")
    if user_domain:
        domain_configs = load_domain_configs()
        cfg = domain_configs.get(user_domain, {})
        for cat_kws in cfg.get("keywords", {}).values():
            for kw in cat_kws:
                if isinstance(kw, str):
                    safe_words.update([kw.title(), kw.upper(), f"{kw.title()}s", f"{kw.upper()}S"])
        for alias in cfg.get("aliases", []):
            safe_words.update([alias.title(), alias.upper()])
        safe_words.update(cfg.get("hallucination_safe_words", []))

    # 4. Context entities
    context_entities = set(re.findall(r'\b[A-Z][a-zA-Z0-9-]{1,}\b', context_text))
    
    # 5. Case-insensitive comparison (Leniency V3)
    safe_words_upper = {sw.upper() for sw in safe_words}
    context_entities_upper = {ce.upper() for ce in context_entities}
    
    # Add ALL alphanumeric words from context to the comparison pool (case-insensitive)
    all_context_words = set(re.findall(r'\w+', context_text.upper()))
    
    hallucinated = []
    for pe in potential_entities:
        pe_upper = pe.upper()
        # 1. Direct match in context or safe words
        if pe_upper in context_entities_upper or pe_upper in safe_words_upper or pe_upper in all_context_words:
            continue
        # 2. Sub-string match (if pe is part of a longer context entity, or vice-versa)
        if any(pe_upper in ce or ce in pe_upper for ce in context_entities_upper):
            continue
        # 3. Sub-string match for safe words (e.g. "Discrepancies" vs "Discrepancy")
        if any(pe_upper.startswith(sw) or sw.startswith(pe_upper) for sw in safe_words_upper if len(sw) > 4):
            continue
        if target_entity.upper() in pe_upper or pe_upper in target_entity.upper():
            continue
        hallucinated.append(pe)
    
    if hallucinated:
        debug_info.append(f"Hallucination detection: Found {len(hallucinated)} potential issues: {list(hallucinated)[:10]}")
    else:
        debug_info.append("Hallucination detection: Passed (0 issues found).")

    # Final decision: If hallucinated, returned blocked message
    if hallucinated and "Data Not Found" not in raw_response:
        # Exclude very short words or purely numeric/symbolic from "truly risky"
        truly_risky = [h for h in hallucinated if len(h) > 3 and any(c.isalpha() for c in h)] 
        if truly_risky:
            print(f"[Response Agent] 🚨 Hallucination detected: {truly_risky}. Forcing Data Not Found.")
            main_res = _DATA_NOT_FOUND_MSG
            # ADD the offending words to the thinking so the user/developer can see them in UI
            debug_info.append(f"🔒 BLOCK REASON: Hallucinated terms: {truly_risky[:5]}")
        else:
            print(f"[Response Agent] 🛡️ Minor hallucination ignored: {hallucinated}")
            main_res = raw_response
    else:
        main_res = raw_response

    # Split report and summary
    main_res = raw_response
    audit_summary = ""
    if "[AUDIT_SUMMARY]" in main_res:
        parts = main_res.split("[AUDIT_SUMMARY]")
        main_res = parts[0].strip()
        if len(parts) > 1:
            audit_summary = parts[1].strip()

    # Fallback Handling: If LLM refused or gave a very short response, 
    # generate a multi-source "Verified Fact Summary".
    if not main_res or "NOT_FOUND" in main_res.upper() or len(main_res) < 10:
        if is_discrepancy:
            # Fallback to state-based audit report if LLM failed to generate one
            state_report = report_text or verdict_dict.get("audit_summary", "A conflict was detected between sources.")
            main_res = f"Note: Conflicts were detected between sources.\n\n{state_report}"
        elif (display_official or display_db or display_informal):
            # Manual multi-source evidence summary fallback
            summary_lines = [f"Based on the VERIFIED CONTEXT, I found the following information for '{target_entity}':"]
            seen_values = set()
            
            for src_list, label in [(display_official, "OFFICIAL"), (display_db, "DATABASE"), (display_informal, "INFORMAL")]:
                for f in src_list:
                    val_clean = f['value'].strip()
                    if val_clean not in seen_values and len(val_clean) > 5:
                        summary_lines.append(f"- **{label} ({f.get('entity', 'General')})**: {val_clean[:1000]}")
                        seen_values.add(val_clean)
            
            if len(summary_lines) > 1:
                main_res = "\n".join(summary_lines)
                print(f"[Response Agent] 🔧 Multi-source evidence summary triggered as fallback.")
            else:
                main_res = _DATA_NOT_FOUND_MSG
        else:
            main_res = _DATA_NOT_FOUND_MSG

    return {
        "generation": main_res,
        "discrepancy_report_summary": audit_summary,
        "thought_process": [f"Synthesized from available context. Evaluated against entity '{target_entity}'."] + debug_info,
    }