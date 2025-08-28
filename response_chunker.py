"""
Response Chunker for Meshtastic AI DM Bot.
Handles splitting AI responses into appropriate chunk sizes for mesh transmission.
"""

import logging
from typing import List, Tuple
import re

logger = logging.getLogger(__name__)

class ResponseChunker:
    """Handles chunking of AI responses for mesh transmission."""
    
    def __init__(self, max_chunk_bytes: int = 180):
        """
        Initialize response chunker.
        
        Args:
            max_chunk_bytes: Maximum bytes per chunk
        """
        self.max_chunk_bytes = max_chunk_bytes
        self.min_chunk_bytes = 10  # Minimum chunk size to avoid tiny fragments
        
        # Word boundary patterns for better chunking
        self.word_boundary_pattern = re.compile(r'\b')
        self.sentence_end_pattern = re.compile(r'[.!?]\s+')
    
    def chunk_text(self, text: str) -> List[str]:
        """
        Split text into chunks of appropriate size.
        
        Args:
            text: Text to chunk
            
        Returns:
            List of text chunks
        """
        if not text:
            return []
        
        # If text fits in one chunk, return as is
        if self._get_byte_size(text) <= self.max_chunk_bytes:
            return [text]
        
        chunks = []
        current_chunk = ""
        
        # Split by sentences first for better readability
        sentences = self._split_into_sentences(text)
        
        for sentence in sentences:
            # Try to add the sentence to current chunk
            test_chunk = current_chunk + sentence
            
            if self._get_byte_size(test_chunk) <= self.max_chunk_bytes:
                current_chunk = test_chunk
            else:
                # Current chunk is full, save it and start new one
                if current_chunk:
                    chunks.append(current_chunk.strip())
                    current_chunk = sentence
                else:
                    # Single sentence is too long, split by words
                    word_chunks = self._chunk_by_words(sentence)
                    chunks.extend(word_chunks)
                    current_chunk = ""
        
        # Add the last chunk if it exists
        if current_chunk:
            chunks.append(current_chunk.strip())
        
        # Validate chunks
        validated_chunks = self._validate_chunks(chunks)
        
        logger.debug(f"Chunked text into {len(validated_chunks)} chunks")
        return validated_chunks
    
    def _split_into_sentences(self, text: str) -> List[str]:
        """
        Split text into sentences for better chunking.
        
        Args:
            text: Text to split
            
        Returns:
            List of sentences
        """
        # Split by sentence endings, but preserve the endings
        sentences = self.sentence_end_pattern.split(text)
        
        # Reattach sentence endings (except for the last one)
        result = []
        for i, sentence in enumerate(sentences[:-1]):
            if sentence.strip():
                result.append(sentence + '. ')
        
        # Add the last sentence
        if sentences[-1].strip():
            result.append(sentences[-1])
        
        return result
    
    def _chunk_by_words(self, text: str) -> List[str]:
        """
        Split long text by words when sentence-based chunking fails.
        
        Args:
            text: Text to split
            
        Returns:
            List of word-based chunks
        """
        words = text.split()
        chunks = []
        current_chunk = ""
        
        for word in words:
            test_chunk = current_chunk + " " + word if current_chunk else word
            
            if self._get_byte_size(test_chunk) <= self.max_chunk_bytes:
                current_chunk = test_chunk
            else:
                # Current chunk is full
                if current_chunk:
                    chunks.append(current_chunk)
                    current_chunk = word
                else:
                    # Single word is too long, truncate it
                    truncated_word = self._truncate_to_bytes(word, self.max_chunk_bytes)
                    chunks.append(truncated_word)
        
        # Add the last chunk
        if current_chunk:
            chunks.append(current_chunk)
        
        return chunks
    
    def _truncate_to_bytes(self, text: str, max_bytes: int) -> str:
        """
        Truncate text to fit within byte limit.
        
        Args:
            text: Text to truncate
            max_bytes: Maximum bytes allowed
            
        Returns:
            Truncated text
        """
        if self._get_byte_size(text) <= max_bytes:
            return text
        
        # Binary search for the right length
        left, right = 0, len(text)
        best_length = 0
        
        while left <= right:
            mid = (left + right) // 2
            test_text = text[:mid]
            
            if self._get_byte_size(test_text) <= max_bytes:
                best_length = mid
                left = mid + 1
            else:
                right = mid - 1
        
        return text[:best_length]
    
    def _get_byte_size(self, text: str) -> int:
        """
        Get the byte size of text when encoded as UTF-8.
        
        Args:
            text: Text to measure
            
        Returns:
            Size in bytes
        """
        return len(text.encode('utf-8'))
    
    def _validate_chunks(self, chunks: List[str]) -> List[str]:
        """
        Validate and clean up chunks.
        
        Args:
            chunks: List of chunks to validate
            
        Returns:
            Validated chunks
        """
        validated = []
        
        for chunk in chunks:
            chunk = chunk.strip()
            if not chunk:
                continue
            
            # Ensure chunk is within size limits
            if self._get_byte_size(chunk) > self.max_chunk_bytes:
                # Truncate if still too long
                chunk = self._truncate_to_bytes(chunk, self.max_chunk_bytes)
            
            # Only add chunks that meet minimum size
            if self._get_byte_size(chunk) >= self.min_chunk_bytes:
                validated.append(chunk)
        
        return validated
    
    def get_chunk_info(self, text: str) -> dict:
        """
        Get information about chunking a text.
        
        Args:
            text: Text to analyze
            
        Returns:
            Dictionary with chunking information
        """
        chunks = self.chunk_text(text)
        total_bytes = sum(self._get_byte_size(chunk) for chunk in chunks)
        
        return {
            'original_text_length': len(text),
            'original_byte_size': self._get_byte_size(text),
            'chunk_count': len(chunks),
            'total_chunked_bytes': total_bytes,
            'chunks': chunks,
            'efficiency': total_bytes / self._get_byte_size(text) if text else 0
        }
    
    def optimize_chunk_size(self, text: str, target_chunks: int) -> int:
        """
        Find optimal chunk size to achieve target number of chunks.
        
        Args:
            text: Text to chunk
            target_chunks: Desired number of chunks
            
        Returns:
            Optimal chunk size in bytes
        """
        if not text or target_chunks <= 1:
            return self.max_chunk_bytes
        
        current_size = self.max_chunk_bytes
        step = current_size // 4
        
        while step > 5:  # Minimum step size
            chunks = self.chunk_text(text)
            
            if len(chunks) == target_chunks:
                return current_size
            elif len(chunks) > target_chunks:
                # Too many chunks, increase size
                current_size += step
            else:
                # Too few chunks, decrease size
                current_size -= step
            
            step = step // 2
        
        return current_size
