package com.integratedai.app

import android.view.Gravity
import android.view.LayoutInflater
import android.view.View
import android.view.ViewGroup
import android.widget.LinearLayout
import android.widget.TextView
import androidx.recyclerview.widget.RecyclerView

class ChatAdapter : RecyclerView.Adapter<ChatAdapter.VH>() {
    private val items = mutableListOf<ChatMessage>()

    fun add(msg: ChatMessage) {
        items.add(msg)
        notifyItemInserted(items.size - 1)
    }

    fun clear() {
        items.clear()
        notifyDataSetChanged()
    }

    fun count(): Int = items.size

    override fun onCreateViewHolder(parent: ViewGroup, viewType: Int): VH {
        val view = LayoutInflater.from(parent.context).inflate(R.layout.item_message, parent, false)
        return VH(view)
    }

    override fun onBindViewHolder(holder: VH, position: Int) {
        val msg = items[position]
        val isUser = msg.role == "user"
        holder.role.text = if (isUser) "YOU" else "INTEGRATED AI"
        holder.root.gravity = if (isUser) Gravity.END else Gravity.START
        holder.role.gravity = if (isUser) Gravity.END else Gravity.START
        holder.body.background = holder.itemView.context.getDrawable(
            if (isUser) R.drawable.user_message_background else R.drawable.ai_message_background
        )
        holder.body.text = msg.text
    }

    override fun getItemCount(): Int = items.size

    class VH(view: View) : RecyclerView.ViewHolder(view) {
        val root: LinearLayout = view as LinearLayout
        val role: TextView = view.findViewById(R.id.roleText)
        val body: TextView = view.findViewById(R.id.bodyText)
    }
}