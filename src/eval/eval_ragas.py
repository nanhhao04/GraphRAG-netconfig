import os
import json
import numpy as np
import pandas as pd
from datetime import datetime
from datasets import Dataset
from ragas import evaluate
from ragas.metrics import (
    faithfulness,
    answer_relevancy,
    context_precision,
    context_recall,
    answer_correctness
)
from ragas.llms import LangchainLLMWrapper
from ragas.embeddings import LangchainEmbeddingsWrapper
import src.connection as connection
from langchain_google_genai import ChatGoogleGenerativeAI
from typing import Any, List, Optional
from langchain_core.callbacks import CallbackManagerForLLMRun
from langchain_core.messages import BaseMessage

EVAL_LOG_DIR = "log/eval"
os.makedirs(EVAL_LOG_DIR, exist_ok=True)


class GeminiNoTemp(ChatGoogleGenerativeAI):
    def _generate(
            self,
            messages: List[BaseMessage],
            stop: Optional[List[str]] = None,
            run_manager: Optional[CallbackManagerForLLMRun] = None,
            **kwargs: Any,
    ):
        if "temperature" in kwargs:
            del kwargs["temperature"]
        return super()._generate(messages, stop=stop, run_manager=run_manager, **kwargs)


class NumpyEncoder(json.JSONEncoder):
    def default(self, obj):
        if isinstance(obj, np.integer):
            return int(obj)
        if isinstance(obj, np.floating):
            return float(obj)
        if isinstance(obj, np.ndarray):
            return obj.tolist()
        return super(NumpyEncoder, self).default(obj)



class NetworkRagasEvaluator:
    def __init__(self):
        try:
            api_key = connection.cfg.get("GOOGLE_API_KEY_2") or os.environ.get("GOOGLE_API_KEY_2")

            ragas_llm = GeminiNoTemp(
                model="gemini-2.5-flash",
                google_api_key=api_key,
            )
            self.ragas_llm = LangchainLLMWrapper(ragas_llm)

        except Exception as e:
            print(f"[Warn] Lỗi khởi tạo GeminiNoTemp: {e}")
            self.ragas_llm = LangchainLLMWrapper(connection.llm)

        self.ragas_embeddings = LangchainEmbeddingsWrapper(connection.embeddings)

        self.metrics_no_ref = [
            faithfulness,
            answer_relevancy
        ]

        self.metrics_with_ref = [
            context_precision,
            context_recall,
            answer_correctness
        ]

    def create_dataset(self, questions, answers, contexts, ground_truths=None):
        data = {
            "question": questions,
            "answer": answers,
            "contexts": contexts,
        }
        if ground_truths:
            data["ground_truth"] = ground_truths

        return Dataset.from_dict(data)

    def evaluate_single_turn(self, question, answer, retrieved_context, ground_truth=None):
        print(f"Evaluating: '{question}'...")

        if isinstance(retrieved_context, str):
            contexts = [[retrieved_context]]
        elif isinstance(retrieved_context, list):
            contexts = [retrieved_context]
        else:
            contexts = [[""]]

        ground_truths = [ground_truth] if ground_truth else None

        dataset = self.create_dataset(
            questions=[question],
            answers=[answer],
            contexts=contexts,
            ground_truths=ground_truths
        )

        active_metrics = self.metrics_no_ref.copy()
        if ground_truth:
            active_metrics.extend(self.metrics_with_ref)

        try:
            results = evaluate(
                dataset=dataset,
                metrics=active_metrics,
                llm=self.ragas_llm,
                embeddings=self.ragas_embeddings
            )

            self.save_results(results)
            return results

        except Exception as e:
            print(f"Ragas Error: {e}")
            return None

    def save_results(self, results):
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        filename = f"{EVAL_LOG_DIR}/ragas_report_{timestamp}.json"

        try:
            if hasattr(results, 'to_pandas'):
                res_dict = results.to_pandas().to_dict(orient="records")[0]
            else:
                res_dict = dict(results)
        except:
            res_dict = {"raw_result": str(results)}

        print("\n" + "=" * 50)
        print("EVALUATION REPORT")
        print("=" * 50)

        scores = {}
        meta_info = {}

        for k, v in res_dict.items():
            if k in ['question', 'answer', 'contexts', 'ground_truth', 'user_input', 'response']:
                meta_info[k] = v
                continue

            try:
                val = float(v)
                scores[k] = val
                print(f"- {k:<25}: {val:.4f}")
            except (ValueError, TypeError):
                meta_info[k] = v

        print("-" * 50)

        try:
            with open(filename, "w", encoding="utf-8") as f:
                full_log = {**scores, **meta_info}
                json.dump(full_log, f, ensure_ascii=False, indent=2, cls=NumpyEncoder)
            print(f"Saved: {filename}")
        except Exception as e:
            print(f"Save Error: {e}")

        print("=" * 50 + "\n")


def run_eval_pipeline(question, answer, context_list, ground_truth=None):
    evaluator = NetworkRagasEvaluator()
    return evaluator.evaluate_single_turn(question, answer, context_list, ground_truth)